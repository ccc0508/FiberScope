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
    pass
