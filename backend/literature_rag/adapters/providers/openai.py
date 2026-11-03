from collections.abc import Sequence
from math import isfinite
from typing import Annotated

from openai import OpenAI
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from literature_rag.application.prompts import system_prompt, evidence_prompt
from literature_rag.domain.errors import ProviderError, ProviderResponseError
from literature_rag.domain.models import Evidence, GeneratedAnswer, GeneratedClaim

NonBlankString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
_OPENAI_API_BASE_URL = "https://api.openai.com/v1"


class _ClaimPayload(BaseModel):
    text: NonBlankString
    citation_refs: list[NonBlankString] = Field(min_length=1)


class _AnswerPayload(BaseModel):
    answer: NonBlankString
    claims: list[_ClaimPayload] = Field(min_length=1)


def _redacted_cause_by_type(exception_type: str) -> RuntimeError:
    return RuntimeError(f"{exception_type}: provider details redacted")


def _finite_float(component: object) -> float | None:
    if type(component) not in (int, float):
        return None
    try:
        converted = float(component)
    except OverflowError:
        return None
    return converted if isfinite(converted) else None


def _client(api_key: str, base_url: str | None, *, timeout: float = 60,
            actor_authorization: str | None = None, proxy_url: str | None = None) -> OpenAI:
    transport = {}
    if proxy_url:
        import httpx
        transport['http_client'] = httpx.Client(proxy=proxy_url, timeout=timeout, trust_env=False)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url or _OPENAI_API_BASE_URL,
        organization="",
        project="",
        max_retries=2,
        timeout=timeout,
        **transport,
    )
    client.organization = None
    client.project = None
    client._custom_headers = ({'x-openai-actor-authorization': actor_authorization}
                              if actor_authorization else {})
    return client


class OpenAIEmbedder:
    def __init__(
        self,
        model: str,
        dimensions: int,
        api_key: str,
        base_url: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._model = model
        self._dimensions = dimensions
        self.client = client if client is not None else _client(api_key, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str], *, timeout_seconds=None) -> list[list[float]]:
        from literature_rag.diagnostics import provider_usage
        self.last_usage = None
        if not texts:
            return []

        requested_texts = list(texts)
        error_type: str | None = None
        response_failure = False
        try:
            client=self.client.with_options(timeout=timeout_seconds,max_retries=0) if timeout_seconds is not None else self.client
            response = client.embeddings.create(
                model=self._model,
                input=requested_texts,
            )
            self.last_usage = provider_usage(response)
        except ValidationError as error:
            error_type = type(error).__name__
            response_failure = True
        except Exception as error:
            error_type = type(error).__name__

        if error_type is not None:
            if response_failure:
                raise ProviderResponseError(
                    f"embedding response failed: {error_type}"
                ) from _redacted_cause_by_type(error_type)
            raise ProviderError(
                f"embedding request failed: {error_type}"
            ) from _redacted_cause_by_type(error_type)

        try:
            items = list(response.data)
        except (AttributeError, TypeError):
            raise ProviderResponseError("embedding response is malformed") from None

        if len(items) != len(requested_texts):
            raise ProviderResponseError("embedding response count or dimension mismatch")

        try:
            indexes = [item.index for item in items]
        except AttributeError:
            raise ProviderResponseError("embedding response indexes are invalid") from None
        if any(type(index) is not int for index in indexes) or sorted(indexes) != list(
            range(len(requested_texts))
        ):
            raise ProviderResponseError("embedding response indexes are invalid")

        try:
            embeddings = [
                list(item.embedding) for item in sorted(items, key=lambda item: item.index)
            ]
        except (AttributeError, TypeError):
            raise ProviderResponseError("embedding response is malformed") from None
        if any(len(embedding) != self._dimensions for embedding in embeddings):
            raise ProviderResponseError("embedding response count or dimension mismatch")

        normalized_embeddings: list[list[float]] = []
        for embedding in embeddings:
            normalized_embedding: list[float] = []
            for component in embedding:
                normalized_component = _finite_float(component)
                if normalized_component is None:
                    raise ProviderResponseError("embedding response components are invalid")
                normalized_embedding.append(normalized_component)
            normalized_embeddings.append(normalized_embedding)
        return normalized_embeddings

    def embed_query(self, text: str, *, timeout_seconds=None) -> list[float]:
        return self.embed_documents([text],timeout_seconds=timeout_seconds)[0]


class OpenAIGenerator:
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        client: OpenAI | None = None,
        *,
        answer_guidance_enabled: bool = False,
        reasoning_effort: str | None = None,
        actor_authorization: str | None = None,
        timeout_seconds: float = 60,
        proxy_url: str | None = None,
        visual_root=None,
    ) -> None:
        if reasoning_effort not in {None, 'low', 'high', 'max'}:
            raise ValueError('unsupported reasoning effort')
        self._model = model
        self.reasoning_effort = reasoning_effort
        self.visual_root = visual_root
        self.system_prompt = system_prompt(answer_guidance_enabled)
        self.client = client if client is not None else _client(api_key, base_url,
            timeout=timeout_seconds, actor_authorization=actor_authorization, proxy_url=proxy_url)

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        from literature_rag.diagnostics import provider_usage
        self.last_usage = None
        self.last_model_info = None
        system = {"role": "system", "content": self.system_prompt}
        user = {
            "role": "user",
            "content": evidence_prompt(question, evidences, retry_feedback),
        }
        sent_images = []
        if any(e.visual_assets for e in evidences):
            if self.visual_root is None:
                raise ProviderResponseError('visual evidence requires its verified source directory')
            from literature_rag.application.visual_evidence import visual_content, VISION_INSTRUCTION
            blocks, sent_images = visual_content(evidences, self.visual_root, user['content'])
            user['content'] = [
                {'type': 'input_text', 'text': b['text']} if b['type'] == 'text' else
                {'type': 'input_image', 'image_url': b['image_url']['url'],
                 'detail': b['image_url']['detail']} for b in blocks
            ]
            system['content'] += '\n\n' + VISION_INSTRUCTION
        error_type: str | None = None
        response_failure = False
        try:
            response = self.client.responses.parse(
                model=self._model,
                input=[system, user],
                text_format=_AnswerPayload,
                store=False,
                **({'reasoning': {'effort': self.reasoning_effort}}
                   if self.reasoning_effort is not None else {}),
            )
            self.last_usage = provider_usage(response)
            self.last_model_info = dict(requested_model=self._model,
                returned_model=getattr(response, 'model', None), wire_api='responses',
                reasoning_effort=self.reasoning_effort, store=False)
            if self.visual_root is not None:
                self.last_model_info.update(image_count=len(sent_images), images=sent_images,
                    input_modality='text_and_images' if sent_images else 'text')
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
            payload = response.output_parsed
        except AttributeError:
            raise ProviderResponseError("generation response is malformed") from None
        if payload is None:
            raise ProviderResponseError("model returned no parsed answer")
        try:
            payload = _AnswerPayload.model_validate(
                payload,
                from_attributes=True,
            )
        except ValidationError as error:
            error_type = type(error).__name__

        if error_type is not None:
            raise ProviderResponseError(
                "model returned invalid parsed answer"
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
