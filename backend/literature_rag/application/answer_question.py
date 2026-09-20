import logging
from collections.abc import Sequence
from time import perf_counter
from typing import Protocol

from literature_rag.application.citations import CitationValidator
from literature_rag.domain.errors import CitationValidationError, ProviderResponseError
from literature_rag.domain.models import Answer, AnswerStatus, Evidence
from literature_rag.ports.protocols import Generator

logger = logging.getLogger(__name__)
CITATION_RETRY_FEEDBACK = (
    "invalid citation placement or reference; keep claim text citation-free, put only supplied "
    "[n] tokens in citation_refs, and cite the answer field"
)
GENERATION_RETRY_FEEDBACK = (
    "invalid generation response; return a valid answer using the supplied evidence"
)
REFUSAL_TEXT = (
    "当前已导入文献中没有检索到足够证据，无法可靠回答该问题。建议补充相关论文或使用更具体的问题。"
)


class Retriever(Protocol):
    def retrieve(
        self,
        question: str,
        top_k: int,
        min_score: float,
    ) -> list[Evidence]:
        raise NotImplementedError


class AnswerService:
    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        validator: CitationValidator,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.validator = validator

    def answer(
        self,
        question: str,
        top_k: int,
        min_score: float,
    ) -> Answer:
        started = perf_counter()
        evidences = self.retriever.retrieve(question, top_k, min_score)
        if not evidences:
            latency_ms = int((perf_counter() - started) * 1000)
            logger.info(
                "answer_refused",
                extra={
                    "stage": "no_evidence",
                    "latency_ms": latency_ms,
                    "model": None,
                    "result_count": 0,
                },
            )
            return self._refusal((), None, latency_ms)

        feedback: str | None = None
        retrieved_chunk_ids = tuple(evidence.chunk_id for evidence in evidences)
        model = self.generator.model_name
        refusal_stage = "invalid_citations"
        reason_code = "citation_validation_failed"
        for _ in range(2):
            try:
                generated = self.generator.generate(question, evidences, feedback)
                validated = self.validator.validate(generated, evidences)
            except CitationValidationError as error:
                feedback = CITATION_RETRY_FEEDBACK
                refusal_stage = "invalid_citations"
                reason_code = "citation_validation_failed"
                logger.warning(
                    "citation_validation_failed",
                    extra={
                        "stage": "citation_validation",
                        "error_type": type(error).__name__,
                        "reason_code": reason_code,
                    },
                )
                continue
            except ProviderResponseError as error:
                feedback = GENERATION_RETRY_FEEDBACK
                refusal_stage = "provider_response_error"
                reason_code = "provider_response_error"
                logger.warning(
                    "generation_response_failed",
                    extra={
                        "stage": "generation",
                        "error_type": type(error).__name__,
                        "reason_code": reason_code,
                    },
                )
                continue

            latency_ms = int((perf_counter() - started) * 1000)
            logger.info(
                "answer_completed",
                extra={
                    "stage": "answered",
                    "latency_ms": latency_ms,
                    "model": model,
                    "result_count": len(validated.citations),
                },
            )
            return Answer(
                status=AnswerStatus.ANSWERED,
                answer=validated.answer,
                rationale=validated.rationale,
                citations=validated.citations,
                retrieved_chunk_ids=retrieved_chunk_ids,
                model=model,
                latency_ms=latency_ms,
            )

        latency_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "answer_refused",
            extra={
                "stage": refusal_stage,
                "latency_ms": latency_ms,
                "model": model,
                "reason_code": reason_code,
                "result_count": 0,
            },
        )
        return self._refusal(retrieved_chunk_ids, model, latency_ms)

    @staticmethod
    def _refusal(
        retrieved_chunk_ids: Sequence[str],
        model: str | None,
        latency_ms: int,
    ) -> Answer:
        return Answer(
            status=AnswerStatus.REFUSED,
            answer=REFUSAL_TEXT,
            rationale=(),
            citations=(),
            retrieved_chunk_ids=tuple(retrieved_chunk_ids),
            model=model,
            latency_ms=latency_ms,
        )
