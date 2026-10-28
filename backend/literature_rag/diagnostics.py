"""Allowlisted, credential-free configuration and provider usage snapshots."""
from hashlib import sha256
from pathlib import Path

from .config import Settings


def configuration_snapshot(env_file: Path):
    settings = Settings(_env_file=env_file)
    root = Path(__file__).resolve().parent
    sources = ['application/prompts.py', 'application/citations.py', 'application/answer_question.py',
               'application/retrieve.py', 'adapters/providers/deepseek.py', 'adapters/providers/openai.py']
    fingerprint = sha256(b'\n'.join((root / source).read_bytes() for source in sources)).hexdigest()
    result = {**{key: getattr(settings, key) for key in (
        'embedding_provider', 'embedding_model', 'embedding_dimensions', 'llm_provider', 'llm_model', 'top_k', 'min_score')},
        'pipeline_version': 'literature-history-v1', 'prompt_pipeline_sha256': fingerprint}
    for key in ('llm_thinking_enabled', 'llm_reasoning_effort'):
        if getattr(settings, key) is not None:
            result[key] = getattr(settings, key)
    return result


def provider_usage(response):
    usage = getattr(response, 'usage', None)
    if usage is None:
        return None
    fields = ('prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens', 'total_tokens')
    result = {key: value for key in fields if type(value := getattr(usage, key, None)) is int and value >= 0}
    for group, names in [('completion_tokens_details', ('reasoning_tokens',)),
                         ('prompt_tokens_details', ('cached_tokens',))]:
        details = getattr(usage, group, None)
        for key in names:
            value = getattr(details, key, None)
            if type(value) is int and value >= 0:
                result[key] = value
    return result or None
