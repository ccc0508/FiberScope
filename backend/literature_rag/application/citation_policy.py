"""Citation identities come from typed successful tool outputs, never prose."""
import re

LITERATURE_CITATION_KINDS = {'source_text', 'source_image'}
CITABLE_KINDS = LITERATURE_CITATION_KINDS | {'experiment_query', 'calculation'}
# Includes malformed public formats and accidental internal IDs for validation.
REFERENCE_TOKEN = re.compile(r'\[(?:\d[\d\s,，、;；\-–—]*|T\d+|txt_[a-fA-F0-9]+)\]')


def citation_records(tool, response):
    if response.get('status') != 'completed':
        return []
    result = response.get('result', {})
    # Calculation types are retained here only for already recorded tool results.
    kind = {'search_literature': 'source_text', 'read_section': 'source_text',
        'read_table': 'source_text', 'view_image': 'source_image',
        'query_experiment_data': 'experiment_query', 'calculate_change': 'calculation', 'convert_units':'calculation'}.get(tool)
    if not kind:
        return []
    if tool == 'search_literature':
        entries = result.get('evidence', [])
    elif tool == 'read_section':
        entries = result.get('sources', [])
    elif tool == 'read_table':
        entries = [result.get('table', {})]
    else:
        entries = [result]
    return [dict(ref=e['ref'], kind=kind, citable=True) for e in entries
        if re.fullmatch(r'\[[1-9][0-9]*\]', str(e.get('ref', '')))]


def invalid_references(answer, allowed):
    # Also catch grouped/range citations and accidental internal IDs. The public
    # format is one numeric reference per bracket: [1][2], never [1,2] or [T15].
    return sorted(set(REFERENCE_TOKEN.findall(answer)) - set(allowed))


def answer_citation_issues(answer, delivered_refs, coverage_report):
    """Check reference identities and the complete absence of inline literature refs."""
    issues = {}
    invalid = invalid_references(answer, delivered_refs)
    if invalid:
        issues['invalid_refs'] = invalid
    if not answer.strip() or not coverage_report:
        return issues

    literature_refs = {ref for ref, record in delivered_refs.items()
                       if record['kind'] in LITERATURE_CITATION_KINDS}
    # The checklist must claim a literature finding backed by a paper source
    # actually delivered to the model. A lookup alone does not require citing.
    if literature_refs and not literature_refs.intersection(REFERENCE_TOKEN.findall(answer)):
        for item in coverage_report['items']:
            if (item['requirement']['role'] == 'literature'
                    and item['status'] in ('verified', 'partial')
                    and literature_refs.intersection(item['reported']['refs'])):
                issues['missing_literature_citations'] = True
                break
    return issues
