"""DeepSeek Chat Completions adapter."""

from collections.abc import Sequence
from typing import Annotated

from openai import OpenAI
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from literature_rag.application.prompts import SYSTEM_PROMPT, evidence_prompt
from literature_rag.domain.errors import ProviderError, ProviderResponseError
from literature_rag.domain.models import Evidence, GeneratedAnswer, GeneratedClaim

NonBlankString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
_DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"
_JSON_OUTPUT_INSTRUCTION = """
Return only one valid JSON object with exactly this structure:
{
  "answer": "a concise complete answer containing citation references",
  "claims": [
    {
      "text": "one independently supported claim",
      "citation_refs": ["[1]"]
    }
  ]
}
Do not wrap the JSON object in Markdown fences or add text before or after it.
""".strip()


class _ClaimPayload(BaseModel):
    text: NonBlankString
    citation_refs: list[NonBlankString] = Field(min_length=1)


class _AnswerPayload(BaseModel):
    answer: NonBlankString
    claims: list[_ClaimPayload] = Field(min_length=1)


def _redacted_cause_by_type(exception_type: str) -> RuntimeError:
    return RuntimeError(f"{exception_type}: provider details redacted")


def _client(api_key: str, base_url: str | None) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url or _DEEPSEEK_API_BASE_URL,
        max_retries=2,
        timeout=60.0,
    )


class DeepSeekGenerator:
    """Generate citation-aware answers with DeepSeek Chat Completions."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self._model = model
        self.client = client if client is not None else _client(api_key, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        messages = [
            {
                "role": "system",
                "content": f"{SYSTEM_PROMPT}\n\n{_JSON_OUTPUT_INSTRUCTION}",
            },
            {
                "role": "user",
                "content": evidence_prompt(question, evidences, retry_feedback),
            },
        ]
        error_type: str | None = None
        response_failure = False
        try:
            response = self.client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except ValidationError as error:
            error_type = type(error).__name__
            response_failure = True
        except Exception as error:
            error_type = type(error).__name__

        if error_type is not None:
            if response_failure:
                raise ProviderResponseError(
                    f"generation response failed: {error_type}"
                ) from _redacted_cause_by_type(error_type)
            raise ProviderError(
                f"generation request failed: {error_type}"
            ) from _redacted_cause_by_type(error_type)

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            raise ProviderResponseError("generation response is malformed") from None
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError("model returned no answer content")

        try:
            payload = _AnswerPayload.model_validate_json(content)
        except ValidationError as error:
            error_type = type(error).__name__
            raise ProviderResponseError(
                "model returned invalid structured answer"
            ) from _redacted_cause_by_type(error_type)

        return GeneratedAnswer(
            answer=payload.answer,
            claims=tuple(
                GeneratedClaim(
                    text=claim.text,
                    citation_refs=tuple(claim.citation_refs),
                )
                for claim in payload.claims
            ),
        )
