import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from literature_rag.domain.errors import CitationValidationError
from literature_rag.domain.models import Citation, Evidence, GeneratedAnswer

_CANONICAL_CITATION_PATTERN = re.compile(r"\[[0-9]+\]")
_ASCII_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
_NONCANONICAL_CITATION_ERROR = "citation references must use canonical format"


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
    ) -> ValidatedAnswer:
        expected_refs = [f"[{index}]" for index in range(1, len(evidences) + 1)]
        if [evidence.ref for evidence in evidences] != expected_refs:
            raise CitationValidationError("evidence references must be unique and sequential")
        if not generated.answer.strip() or not generated.claims:
            raise CitationValidationError("answer and claims must not be empty")

        by_ref = {evidence.ref: evidence for evidence in evidences}
        used: set[str] = set()
        seen_claims: set[str] = set()
        rationale: list[str] = []
        for claim in generated.claims:
            normalized_claim_text = claim.text.strip()
            if not normalized_claim_text:
                raise CitationValidationError("claim text must not be empty")
            if claim.text.splitlines() != [claim.text]:
                raise CitationValidationError("claim text must be a single line")
            _, stripped_claim_refs, normalized_claim_refs = _citation_tokens(claim.text)
            if stripped_claim_refs or normalized_claim_refs:
                raise CitationValidationError("claim text must not contain citation references")
            if not claim.citation_refs:
                raise CitationValidationError("every claim requires a citation")
            if any(not isinstance(ref, str) for ref in claim.citation_refs):
                raise CitationValidationError("claim citation references must be strings")
            if len(set(claim.citation_refs)) != len(claim.citation_refs):
                raise CitationValidationError("claim citation references must be unique")
            unknown = [ref for ref in claim.citation_refs if ref not in by_ref]
            if unknown:
                raise CitationValidationError(f"unknown citation references: {unknown}")
            if normalized_claim_text in seen_claims:
                raise CitationValidationError("duplicate claims are not allowed")
            seen_claims.add(normalized_claim_text)
            used.update(claim.citation_refs)
            rationale.append(f"{claim.text} {' '.join(claim.citation_refs)}")

        answer_refs, stripped_answer_refs, normalized_answer_refs = _citation_tokens(
            generated.answer
        )
        if stripped_answer_refs != answer_refs or normalized_answer_refs != answer_refs:
            raise CitationValidationError(_NONCANONICAL_CITATION_ERROR)
        if not answer_refs:
            raise CitationValidationError("answer requires at least one citation")
        unknown = [ref for ref in answer_refs if ref not in by_ref]
        if unknown:
            raise CitationValidationError(f"unknown citation references: {unknown}")
        if any(ref not in used for ref in answer_refs):
            raise CitationValidationError("answer citation references must be declared by claims")

        citations = tuple(
            Citation(
                ref=evidence.ref,
                filename=evidence.filename,
                page_start=evidence.page_start,
                page_end=evidence.page_end,
                chunk_id=evidence.chunk_id,
            )
            for evidence in evidences
            if evidence.ref in used
        )
        return ValidatedAnswer(
            answer="\n".join(rationale),
            rationale=tuple(rationale),
            citations=citations,
        )
