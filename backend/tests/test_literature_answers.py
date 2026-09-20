import logging
from collections.abc import Sequence

import pytest

import literature_rag.application.answer_question as answer_question_module
from literature_rag.application.answer_question import REFUSAL_TEXT, AnswerService
from literature_rag.application.citations import CitationValidator
from literature_rag.domain.errors import (
    InfrastructureError,
    ProviderError,
    ProviderResponseError,
)
from literature_rag.domain.models import (
    Answer,
    AnswerStatus,
    Citation,
    Evidence,
    GeneratedAnswer,
    GeneratedClaim,
)


class StubRetriever:
    def __init__(self, evidences: Sequence[Evidence]) -> None:
        self.evidences = list(evidences)
        self.calls: list[tuple[str, int, float]] = []

    def retrieve(self, question: str, top_k: int, min_score: float) -> list[Evidence]:
        self.calls.append((question, top_k, min_score))
        return list(self.evidences)


class SequenceGenerator:
    model_name = "answer-model"

    def __init__(self, responses: Sequence[GeneratedAnswer | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[Evidence, ...], str | None]] = []

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        self.calls.append((question, tuple(evidences), retry_feedback))
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class ModelNameExplodingGenerator:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        raise AssertionError("model_name must not be accessed without evidence")

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        self.calls += 1
        raise AssertionError("generate must not be called without evidence")


class FailingRetriever:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def retrieve(self, question: str, top_k: int, min_score: float) -> list[Evidence]:
        self.calls += 1
        raise self.error


def make_evidence(ref: str = "[1]", chunk_id: str = "chk1") -> Evidence:
    return Evidence(
        ref=ref,
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        filename=f"{chunk_id}.pdf",
        page_start=4,
        page_end=4,
        text="evidence",
        score=0.9,
    )


def test_answer_refuses_without_evidence_and_does_not_call_generator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retriever = StubRetriever([])
    generator = ModelNameExplodingGenerator()
    service = AnswerService(retriever, generator, CitationValidator())
    caplog.set_level(logging.INFO, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer == Answer(
        status=AnswerStatus.REFUSED,
        answer="当前已导入文献中没有检索到足够证据，无法可靠回答该问题。建议补充相关论文或使用更具体的问题。",
        rationale=(),
        citations=(),
        retrieved_chunk_ids=(),
        model=None,
        latency_ms=answer.latency_ms,
    )
    assert answer.answer == REFUSAL_TEXT
    assert retriever.calls == [("Question?", 8, 0.35)]
    assert generator.calls == 0
    refused = next(record for record in caplog.records if record.message == "answer_refused")
    assert refused.stage == "no_evidence"
    assert refused.result_count == 0


def test_answer_returns_validated_citations_and_all_retrieved_chunks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    evidences = [make_evidence(), make_evidence("[2]", "chk2")]
    retriever = StubRetriever(evidences)
    generator = SequenceGenerator(
        [
            GeneratedAnswer(
                answer="Answer [1]",
                claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
            )
        ]
    )
    service = AnswerService(retriever, generator, CitationValidator())
    caplog.set_level(logging.INFO, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.answer == "Claim [1]"
    assert answer.rationale == ("Claim [1]",)
    assert answer.citations == (
        Citation(
            ref="[1]",
            filename="chk1.pdf",
            page_start=4,
            page_end=4,
            chunk_id="chk1",
        ),
    )
    assert answer.retrieved_chunk_ids == ("chk1", "chk2")
    assert answer.model == "answer-model"
    assert generator.calls == [("Question?", tuple(evidences), None)]
    completed = next(record for record in caplog.records if record.message == "answer_completed")
    assert completed.stage == "answered"
    assert completed.model == "answer-model"
    assert completed.result_count == 1
    assert isinstance(completed.latency_ms, int)


def test_answer_service_never_exposes_uncited_generated_answer_text() -> None:
    generator = SequenceGenerator(
        [
            GeneratedAnswer(
                answer="Supported [1]. Fabricated uncited conclusion.",
                claims=(GeneratedClaim(text="Supported", citation_refs=("[1]",)),),
            )
        ]
    )
    service = AnswerService(StubRetriever([make_evidence()]), generator, CitationValidator())

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.answer == "Supported [1]"
    assert "Fabricated" not in answer.answer


def test_answer_retries_invalid_citations_then_refuses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    evidence = make_evidence()
    malicious_ref = "[999]"
    invalid = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="Claim", citation_refs=(malicious_ref,)),),
    )
    retriever = StubRetriever([evidence])
    generator = SequenceGenerator([invalid, invalid])
    service = AnswerService(retriever, generator, CitationValidator())
    caplog.set_level(logging.INFO, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.REFUSED
    assert answer.answer == REFUSAL_TEXT
    assert answer.rationale == ()
    assert answer.citations == ()
    assert answer.retrieved_chunk_ids == ("chk1",)
    assert answer.model == "answer-model"
    assert len(generator.calls) == 2
    assert generator.calls[0][2] is None
    assert generator.calls[1][2] == (
        "invalid citation placement or reference; keep claim text citation-free, put only supplied "
        "[n] tokens in citation_refs, and cite the answer field"
    )
    assert malicious_ref not in generator.calls[1][2]
    failures = [
        record for record in caplog.records if record.message == "citation_validation_failed"
    ]
    assert len(failures) == 2
    assert all(record.stage == "citation_validation" for record in failures)
    assert all(record.error_type == "CitationValidationError" for record in failures)
    assert all(record.reason_code == "citation_validation_failed" for record in failures)
    assert malicious_ref not in caplog.text
    refused = next(record for record in caplog.records if record.message == "answer_refused")
    assert refused.levelno == logging.INFO
    assert refused.stage == "invalid_citations"
    assert refused.model == "answer-model"


def test_answer_uses_fixed_safe_retry_feedback_constants() -> None:
    assert answer_question_module.CITATION_RETRY_FEEDBACK == (
        "invalid citation placement or reference; keep claim text citation-free, put only supplied "
        "[n] tokens in citation_refs, and cite the answer field"
    )
    assert answer_question_module.GENERATION_RETRY_FEEDBACK == (
        "invalid generation response; return a valid answer using the supplied evidence"
    )


def test_answer_succeeds_after_invalid_citation_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    evidence = make_evidence()
    malicious_ref = "[999]"
    invalid = GeneratedAnswer(
        answer="Unsupported",
        claims=(GeneratedClaim(text="Unsupported", citation_refs=(malicious_ref,)),),
    )
    valid = GeneratedAnswer(
        answer="Answer [1]",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )
    generator = SequenceGenerator([invalid, valid])
    service = AnswerService(StubRetriever([evidence]), generator, CitationValidator())
    caplog.set_level(logging.WARNING, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.ANSWERED
    assert len(generator.calls) == 2
    assert generator.calls[1][2] == (
        "invalid citation placement or reference; keep claim text citation-free, put only supplied "
        "[n] tokens in citation_refs, and cite the answer field"
    )
    assert malicious_ref not in generator.calls[1][2]
    failure = next(
        record for record in caplog.records if record.message == "citation_validation_failed"
    )
    assert failure.reason_code == "citation_validation_failed"
    assert malicious_ref not in caplog.text


def test_answer_retries_answer_without_citation_then_succeeds() -> None:
    evidence = make_evidence()
    uncited = GeneratedAnswer(
        answer="Unsupported answer",
        claims=(GeneratedClaim(text="Supported claim", citation_refs=("[1]",)),),
    )
    cited = GeneratedAnswer(
        answer="Supported answer [1]",
        claims=(GeneratedClaim(text="Supported claim", citation_refs=("[1]",)),),
    )
    generator = SequenceGenerator([uncited, cited])
    service = AnswerService(StubRetriever([evidence]), generator, CitationValidator())

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.answer == "Supported claim [1]"
    assert len(generator.calls) == 2
    assert generator.calls[0][2] is None
    assert generator.calls[1][2] == answer_question_module.CITATION_RETRY_FEEDBACK


def test_answer_refuses_after_two_answers_without_citations() -> None:
    evidence = make_evidence()
    uncited = GeneratedAnswer(
        answer="Unsupported answer",
        claims=(GeneratedClaim(text="Supported claim", citation_refs=("[1]",)),),
    )
    generator = SequenceGenerator([uncited, uncited])
    service = AnswerService(StubRetriever([evidence]), generator, CitationValidator())

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.REFUSED
    assert answer.answer == REFUSAL_TEXT
    assert answer.citations == ()
    assert len(generator.calls) == 2
    assert generator.calls[1][2] == answer_question_module.CITATION_RETRY_FEEDBACK


def test_answer_retries_provider_response_error_then_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_error = ProviderResponseError("provider secret response")
    valid = GeneratedAnswer(
        answer="Answer [1]",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )
    generator = SequenceGenerator([provider_error, valid])
    service = AnswerService(
        StubRetriever([make_evidence()]),
        generator,
        CitationValidator(),
    )
    caplog.set_level(logging.WARNING, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.ANSWERED
    assert len(generator.calls) == 2
    assert generator.calls[0][2] is None
    assert generator.calls[1][2] == (
        "invalid generation response; return a valid answer using the supplied evidence"
    )
    failure = next(
        record for record in caplog.records if record.reason_code == "provider_response_error"
    )
    assert failure.error_type == "ProviderResponseError"
    assert "provider secret response" not in caplog.text
    assert "provider secret response" not in generator.calls[1][2]


def test_answer_refuses_after_two_provider_response_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    generator = SequenceGenerator(
        [
            ProviderResponseError("first provider secret"),
            ProviderResponseError("second provider secret"),
        ]
    )
    service = AnswerService(
        StubRetriever([make_evidence()]),
        generator,
        CitationValidator(),
    )
    caplog.set_level(logging.INFO, logger="literature_rag.application.answer_question")

    answer = service.answer("Question?", top_k=8, min_score=0.35)

    assert answer.status is AnswerStatus.REFUSED
    assert answer.retrieved_chunk_ids == ("chk1",)
    assert answer.model == "answer-model"
    assert len(generator.calls) == 2
    assert generator.calls[1][2] == (
        "invalid generation response; return a valid answer using the supplied evidence"
    )
    failures = [
        record
        for record in caplog.records
        if getattr(record, "reason_code", None) == "provider_response_error"
    ]
    assert len(failures) == 3
    assert "first provider secret" not in caplog.text
    assert "second provider secret" not in caplog.text


def test_answer_propagates_provider_error_without_retry() -> None:
    provider_error = ProviderError("request failed")
    generator = SequenceGenerator([provider_error])
    service = AnswerService(
        StubRetriever([make_evidence()]),
        generator,
        CitationValidator(),
    )

    with pytest.raises(ProviderError) as exc_info:
        service.answer("Question?", top_k=8, min_score=0.35)

    assert exc_info.value is provider_error
    assert len(generator.calls) == 1


def test_answer_propagates_retrieval_error_without_accessing_generator() -> None:
    retrieval_error = InfrastructureError("retrieval failed")
    retriever = FailingRetriever(retrieval_error)
    generator = ModelNameExplodingGenerator()
    service = AnswerService(retriever, generator, CitationValidator())

    with pytest.raises(InfrastructureError) as exc_info:
        service.answer("Question?", top_k=8, min_score=0.35)

    assert exc_info.value is retrieval_error
    assert retriever.calls == 1
    assert generator.calls == 0
