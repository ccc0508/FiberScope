class LiteratureRagError(Exception):
    """Base error shown through a stable CLI policy."""


class InputError(LiteratureRagError):
    pass


class DocumentError(LiteratureRagError):
    pass


class ProviderError(LiteratureRagError):
    pass


class ProviderResponseError(ProviderError):
    pass


class InfrastructureError(LiteratureRagError):
    pass


class CitationValidationError(LiteratureRagError):
    def __init__(self, message: str, *, rule_code: str | None = None,
                 field: str | None = None, claim_index: int | None = None):
        super().__init__(message)
        self.rule_code = rule_code
        self.field = field
        self.claim_index = claim_index
