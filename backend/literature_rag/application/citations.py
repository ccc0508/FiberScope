import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json

from literature_rag.domain.errors import CitationValidationError
from literature_rag.domain.models import Citation, Evidence, GeneratedAnswer

_CANONICAL_CITATION_PATTERN = re.compile(r"\[[0-9]+\]")
_ASCII_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
_NONCANONICAL_CITATION_ERROR = "citation references must use canonical format"
VALIDATION_TRACE_VERSION = 'citation-validation-trace-v1'
# Fixed messages only: exception strings may contain untrusted reference tokens.
RULE_MESSAGES = {
    'evidence_reference_sequence': '证据编号不唯一、不连续或顺序不正确。',
    'empty_answer_or_claims': 'answer或claims为空。',
    'empty_claim_text': '陈述正文为空。',
    'multiline_claim_text': '单条陈述包含换行。',
    'inline_claim_reference': '陈述正文直接包含引用标记；引用应放在citation_refs中。',
    'missing_claim_reference': '陈述未填写引用。',
    'non_string_claim_reference': '陈述的引用编号不是字符串。',
    'duplicate_claim_reference': '同一陈述重复填写引用编号。',
    'unknown_claim_reference': '陈述引用了未提供的证据编号。',
    'duplicate_claim': '陈述内容重复。',
    'noncanonical_answer_reference': 'answer中的引用标记不是标准[n]格式。',
    'missing_answer_reference': 'answer中没有引用标记。',
    'unknown_answer_reference': 'answer引用了未提供的证据编号。',
    'undeclared_answer_reference': 'answer中的引用未在claims中声明。',
}


def _numeric_bracket_tokens(text: str) -> list[str]:
    return [
        candidate
        for candidate in _ASCII_BRACKET_PATTERN.findall(text)
        if any(unicodedata.numeric(character, None) is not None for character in candidate)
    ]


def _citation_tokens(text: str) -> tuple[list[str], list[str], list[str]]:
    canonical = _CANONICAL_CITATION_PATTERN.findall(text)
    stripped_view = "".join(
        character for character in text if unicodedata.category(character) != "Cf"
    )
    normalized_view = unicodedata.normalize("NFKC", stripped_view)
    return (
        canonical,
        _numeric_bracket_tokens(stripped_view),
        _numeric_bracket_tokens(normalized_view),
    )


@dataclass(frozen=True, slots=True)
class ValidatedAnswer:
    answer: str
    rationale: tuple[str, ...]
    citations: tuple[Citation, ...]


class CitationValidator:
    def validate(
        self,
        generated: GeneratedAnswer,
        evidences: Sequence[Evidence],
        *, allow_sparse_refs: bool = False,
    ) -> ValidatedAnswer:
        expected_refs = [f"[{index}]" for index in range(1, len(evidences) + 1)]
        actual_refs = [evidence.ref for evidence in evidences]
        if allow_sparse_refs and all(re.fullmatch(r'\[[1-9][0-9]*\]', ref) for ref in actual_refs):
            expected_refs = sorted(set(actual_refs), key=lambda ref:int(ref[1:-1]))
        if actual_refs != expected_refs:
            raise CitationValidationError("evidence references must be unique and sequential",
                rule_code='evidence_reference_sequence', field='evidences.ref')
        if not generated.answer.strip() or not generated.claims:
            raise CitationValidationError("answer and claims must not be empty",
                rule_code='empty_answer_or_claims', field='answer' if not generated.answer.strip() else 'claims')

        by_ref = {evidence.ref: evidence for evidence in evidences}
        used: set[str] = set()
        seen_claims: set[str] = set()
        rationale: list[str] = []
        for index, claim in enumerate(generated.claims):
            normalized_claim_text = claim.text.strip()
            if not normalized_claim_text:
                raise CitationValidationError("claim text must not be empty",
                    rule_code='empty_claim_text', field=f'claims[{index}].text', claim_index=index)
            if claim.text.splitlines() != [claim.text]:
                raise CitationValidationError("claim text must be a single line",
                    rule_code='multiline_claim_text', field=f'claims[{index}].text', claim_index=index)
            _, stripped_claim_refs, normalized_claim_refs = _citation_tokens(claim.text)
            if stripped_claim_refs or normalized_claim_refs:
                raise CitationValidationError("claim text must not contain citation references",
                    rule_code='inline_claim_reference', field=f'claims[{index}].text', claim_index=index)
            if not claim.citation_refs:
                raise CitationValidationError("every claim requires a citation",
                    rule_code='missing_claim_reference', field=f'claims[{index}].citation_refs', claim_index=index)
            if any(not isinstance(ref, str) for ref in claim.citation_refs):
                raise CitationValidationError("claim citation references must be strings",
                    rule_code='non_string_claim_reference', field=f'claims[{index}].citation_refs', claim_index=index)
            if len(set(claim.citation_refs)) != len(claim.citation_refs):
                raise CitationValidationError("claim citation references must be unique",
                    rule_code='duplicate_claim_reference', field=f'claims[{index}].citation_refs', claim_index=index)
            unknown = [ref for ref in claim.citation_refs if ref not in by_ref]
            if unknown:
                raise CitationValidationError(f"unknown citation references: {unknown}",
                    rule_code='unknown_claim_reference', field=f'claims[{index}].citation_refs', claim_index=index)
            if normalized_claim_text in seen_claims:
                raise CitationValidationError("duplicate claims are not allowed",
                    rule_code='duplicate_claim', field=f'claims[{index}].text', claim_index=index)
            seen_claims.add(normalized_claim_text)
            used.update(claim.citation_refs)
            rationale.append(f"{claim.text} {' '.join(claim.citation_refs)}")

        answer_refs, stripped_answer_refs, normalized_answer_refs = _citation_tokens(
            generated.answer
        )
        if stripped_answer_refs != answer_refs or normalized_answer_refs != answer_refs:
            raise CitationValidationError(_NONCANONICAL_CITATION_ERROR,
                rule_code='noncanonical_answer_reference', field='answer')
        if not answer_refs:
            raise CitationValidationError("answer requires at least one citation",
                rule_code='missing_answer_reference', field='answer')
        unknown = [ref for ref in answer_refs if ref not in by_ref]
        if unknown:
            raise CitationValidationError(f"unknown citation references: {unknown}",
                rule_code='unknown_answer_reference', field='answer')
        if any(ref not in used for ref in answer_refs):
            raise CitationValidationError("answer citation references must be declared by claims",
                rule_code='undeclared_answer_reference', field='answer')

        citations = tuple(
            Citation(
                ref=evidence.ref,
                filename=evidence.filename,
                page_start=evidence.page_start,
                page_end=evidence.page_end,
                chunk_id=evidence.chunk_id,
                source_chunks=evidence.source_chunks,
                visual_assets=evidence.visual_assets,
            )
            for evidence in evidences
            if evidence.ref in used
        )
        return ValidatedAnswer(
            answer="\n".join(rationale),
            rationale=tuple(rationale),
            citations=citations,
        )


class RecordingCitationValidator(CitationValidator):
    """Per-question observer; validation, retry feedback and accepted output stay unchanged."""
    def __init__(self, attempt_number: Callable[[], int] | None = None):
        self.attempts: list[dict] = []
        self.attempt_number = attempt_number

    def snapshot(self) -> dict:
        # Return a detached JSON snapshot, including failed drafts after a successful retry.
        return json.loads(json.dumps(dict(version=VALIDATION_TRACE_VERSION,
            scope='structural_validation_only', first_failure_only=True,
            draft_policy='failed_structured_generations_only', attempts=self.attempts), ensure_ascii=False))

    def validate(self, generated: GeneratedAnswer, evidences: Sequence[Evidence]) -> ValidatedAnswer:
        attempt = self.attempt_number() if self.attempt_number else len(self.attempts) + 1
        record = dict(attempt=attempt, status='passed', supplied_refs=[e.ref for e in evidences],
                      rule_code=None, message=None, field=None, claim_index=None,
                      draft=None, draft_sha256=None)
        try:
            validated = super().validate(generated, evidences)
        except CitationValidationError as error:
            known = error.rule_code in RULE_MESSAGES
            draft = dict(answer=generated.answer,
                claims=[dict(text=c.text, citation_refs=list(c.citation_refs)) for c in generated.claims])
            record.update(status='failed', rule_code=error.rule_code if known else 'unknown_rule',
                message=RULE_MESSAGES[error.rule_code] if known else '引用校验失败，具体规则未记录。',
                field=error.field if known else None, claim_index=error.claim_index if known else None,
                draft=draft, draft_sha256=sha256(json.dumps(draft, ensure_ascii=False,
                    sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest())
            self.attempts.append(record)
            raise
        self.attempts.append(record)
        return validated
