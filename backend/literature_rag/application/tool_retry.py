"""Bounded retries for read-only tools; only explicit transient failures retry unchanged."""
import json
from .tools import INPUT

TRANSIENT = {'tool_timeout', 'TimeoutError', 'TimeoutException', 'ReadTimeout', 'ConnectTimeout',
             'ConnectionError', 'ConnectError', 'APIConnectionError', 'APITimeoutError',
             'RemoteProtocolError', 'InternalServerError', 'ServiceUnavailableError', 'RateLimitError'}
PARAMETER_ERRORS = {'invalid_arguments', 'invalid_query', 'unsupported_sql', 'unknown_section',
                    'unknown_document', 'unknown_asset', 'ValueError'}


def signature(request):
    return json.dumps({k:v for k,v in request.items() if k != 'reason'}, sort_keys=True)


class ToolRetryPolicy:
    def __init__(self):
        self.failures = []
        self.transient_counts = {}

    def observe(self, request, result):
        if result.get('status') == 'completed':
            return
        code = result.get('error_code', '')
        kind = 'parameter' if code in PARAMETER_ERRORS or result.get('status') == 'invalid_arguments' else 'refused'
        sqlstate = result.get('sqlstate') or ''
        if code in TRANSIENT or (code == 'database_query_failed' and
                                (sqlstate.startswith('08') or sqlstate in {'40001', '40P01', '57014', '57P03'})):
            kind = 'transient'
        # A schema rejection can involve reason itself. Validate the corrected
        # request locally; never use cosmetic reason changes to retry execution errors.
        invalid_schema = False
        if kind == 'parameter':
            try: INPUT.validate_python(request)
            except ValueError: invalid_schema = True
        self.failures.append((dict(request), signature(request), kind, code, invalid_schema))
        if kind == 'transient':
            key = signature(request)
            self.transient_counts[key] = self.transient_counts.get(key, 0) + 1

    def block(self, request):
        key = signature(request)
        for previous, oldkey, kind, code, invalid_schema in reversed(self.failures):
            if previous.get('tool') != request.get('tool'):
                continue
            if invalid_schema:
                # Changed unrelated fields must not bypass a still-invalid schema.
                try: INPUT.validate_python(request)
                except ValueError:
                    return self.denied('parameters_not_corrected', code,
                        'Correct the invalid/missing tool parameters before retrying; changing reason alone is insufficient unless reason was invalid.')
                continue
            if oldkey != key:
                continue
            if kind == 'transient':
                if self.transient_counts[key] <= 1:
                    continue
                return self.denied('transient_retry_exhausted', code,
                    'One unchanged retry after a transient failure is allowed; it has been used. Retain the gap or use another valid path.')
            return self.denied('parameters_not_corrected' if kind == 'parameter' else 'non_retryable_failure', code,
                'This operation previously failed. Correct relevant operation parameters or choose another permitted path; do not repeat it unchanged.')
        return None

    @staticmethod
    def denied(code, previous, notice):
        return dict(status='blocked', error_code=code, previous_error_code=previous, notice=notice)
