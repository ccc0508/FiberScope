import pytest

from literature_rag.application.citations import CitationValidator, ValidatedAnswer
from literature_rag.domain.errors import CitationValidationError
from literature_rag.domain.models import (
    Citation,
    Evidence,
    GeneratedAnswer,
    GeneratedClaim,
)


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


def test_citation_validator_builds_rationale_and_authoritative_citation() -> None:
    generated = GeneratedAnswer(
        answer="  Answer [1] then [2]  ",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[2]", "[1]")),),
    )
    evidences = [make_evidence(), make_evidence("[2]", "chk2")]

    validated = CitationValidator().validate(generated, evidences)

    assert validated == ValidatedAnswer(
        answer="Claim [2] [1]",
        rationale=("Claim [2] [1]",),
        citations=(
            Citation(
                ref="[1]",
                filename="chk1.pdf",
                page_start=4,
                page_end=4,
                chunk_id="chk1",
            ),
            Citation(
                ref="[2]",
                filename="chk2.pdf",
                page_start=4,
                page_end=4,
                chunk_id="chk2",
            ),
        ),
    )


def test_citation_validator_never_exposes_uncited_generated_answer_text() -> None:
    generated = GeneratedAnswer(
        answer="Supported [1]. Fabricated uncited conclusion.",
        claims=(GeneratedClaim(text="Supported", citation_refs=("[1]",)),),
    )

    validated = CitationValidator().validate(generated, [make_evidence()])

    assert validated.answer == "Supported [1]"
    assert "Fabricated" not in validated.answer


def test_citation_validator_renders_claims_in_order_with_references_on_each_line() -> None:
    generated = GeneratedAnswer(
        answer="Summary [1] [2]",
        claims=(
            GeneratedClaim(text="First claim", citation_refs=("[2]",)),
            GeneratedClaim(text="Second claim", citation_refs=("[1]", "[2]")),
        ),
    )

    validated = CitationValidator().validate(
        generated,
        [make_evidence(), make_evidence("[2]", "chk2")],
    )

    assert validated.answer == "First claim [2]\nSecond claim [1] [2]"
    assert validated.rationale == ("First claim [2]", "Second claim [1] [2]")


@pytest.mark.parametrize(
    "evidences",
    [
        [make_evidence(), make_evidence("[1]", "chk2")],
        [make_evidence("[2]", "chk2"), make_evidence()],
        [make_evidence("1")],
    ],
    ids=["duplicate", "out-of-order", "noncanonical"],
)
def test_citation_validator_requires_unique_sequential_evidence_references(
    evidences: list[Evidence],
) -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^evidence references must be unique and sequential$",
    ):
        CitationValidator().validate(generated, evidences)


@pytest.mark.parametrize(
    "generated",
    [
        GeneratedAnswer(
            answer="   ",
            claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
        ),
        GeneratedAnswer(answer="Answer", claims=()),
    ],
    ids=["blank-answer", "empty-claims"],
)
def test_citation_validator_rejects_empty_answer_or_claims(
    generated: GeneratedAnswer,
) -> None:
    with pytest.raises(
        CitationValidationError,
        match=r"^answer and claims must not be empty$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


def test_citation_validator_rejects_claim_without_references() -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="Claim", citation_refs=()),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^every claim requires a citation$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


def test_citation_validator_rejects_blank_claim_text() -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="   ", citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim text must not be empty$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    "claim_text",
    [
        "First line\nSecond line",
        "First line\rSecond line",
        "First line\u0085Second line",
        "First line\u2028Second line",
    ],
    ids=["line-feed", "carriage-return", "next-line", "line-separator"],
)
def test_citation_validator_rejects_multiline_claim_text(claim_text: str) -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text=claim_text, citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim text must be a single line$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    "claim_text",
    ["Injected [99]", "Claim [1]", "Injected [ 99 ]", "Claim [ 1 ]"],
)
def test_citation_validator_rejects_inline_claim_citations(claim_text: str) -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text=claim_text, citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim text must not contain citation references$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    "citation_like",
    [
        "[\u200b99\u200b]",
        "[\u206099\u2060]",
        "[\ufeff99\ufeff]",
        "[\u200c99\u200c]",
        "[\u200b1\u200b]",
        "［９９］",
        "［１］",
        "[Section 1]",
        "[❾]",
        "[➈]",
        "[Ⅸ]",
        "[⑨]",
        "[₉]",
    ],
    ids=[
        "zero-width-space",
        "word-joiner",
        "bom",
        "zwnj",
        "obfuscated-known",
        "fullwidth-unknown",
        "fullwidth-known",
        "descriptive",
        "dingbat-negative-circled",
        "dingbat-circled",
        "roman-numeral",
        "circled-number",
        "subscript-number",
    ],
)
def test_citation_validator_rejects_obfuscated_inline_claim_citations(
    citation_like: str,
) -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(
            GeneratedClaim(
                text=f"Injected {citation_like}",
                citation_refs=("[1]",),
            ),
        ),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim text must not contain citation references$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


def test_citation_validator_requires_string_claim_references() -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]", 2)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim citation references must be strings$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


def test_citation_validator_rejects_duplicate_claim_references() -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]", "[1]")),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^claim citation references must be unique$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    "claims",
    [
        (
            GeneratedClaim(text="Claim", citation_refs=("[1]",)),
            GeneratedClaim(text="Claim", citation_refs=("[2]",)),
        ),
        (
            GeneratedClaim(text="Claim", citation_refs=("[1]", "[2]")),
            GeneratedClaim(text="Claim", citation_refs=("[2]", "[1]")),
        ),
        (
            GeneratedClaim(text="Claim", citation_refs=("[1]",)),
            GeneratedClaim(text="  Claim  ", citation_refs=("[2]",)),
        ),
    ],
    ids=["different-refs", "reordered-refs", "surrounding-whitespace"],
)
def test_citation_validator_rejects_normalized_duplicate_claims(
    claims: tuple[GeneratedClaim, GeneratedClaim],
) -> None:
    generated = GeneratedAnswer(answer="Answer", claims=claims)

    with pytest.raises(
        CitationValidationError,
        match=r"^duplicate claims are not allowed$",
    ):
        CitationValidator().validate(
            generated,
            [make_evidence(), make_evidence("[2]", "chk2")],
        )


def test_citation_validator_rejects_unknown_references() -> None:
    generated = GeneratedAnswer(
        answer="Answer",
        claims=(
            GeneratedClaim(text="First claim", citation_refs=("[99]",)),
            GeneratedClaim(text="Second claim", citation_refs=("[88]",)),
        ),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^unknown citation references: \['\[99\]'\]$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ("Answer [99]", "unknown citation references: ['[99]']"),
        ("Answer [ 99 ]", "citation references must use canonical format"),
        ("Answer [ 1 ]", "citation references must use canonical format"),
    ],
    ids=["canonical-unknown", "spaced-unknown", "spaced-noncanonical"],
)
def test_citation_validator_rejects_unknown_answer_references(
    answer: str,
    message: str,
) -> None:
    generated = GeneratedAnswer(
        answer=answer,
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )

    with pytest.raises(CitationValidationError) as exc_info:
        CitationValidator().validate(generated, [make_evidence()])

    assert str(exc_info.value) == message


def test_citation_validator_rejects_answer_without_canonical_citation() -> None:
    generated = GeneratedAnswer(
        answer="Answer without a citation",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^answer requires at least one citation$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


@pytest.mark.parametrize(
    "citation_like",
    [
        "[\u200b99\u200b]",
        "[\u206099\u2060]",
        "[\ufeff99\ufeff]",
        "[\u200c99\u200c]",
        "[\u200b1\u200b]",
        "［９９］",
        "［１］",
        "[Section 1]",
        "[❾]",
        "[➈]",
        "[Ⅸ]",
        "[⑨]",
        "[₉]",
    ],
    ids=[
        "zero-width-space",
        "word-joiner",
        "bom",
        "zwnj",
        "obfuscated-known",
        "fullwidth-unknown",
        "fullwidth-known",
        "descriptive",
        "dingbat-negative-circled",
        "dingbat-circled",
        "roman-numeral",
        "circled-number",
        "subscript-number",
    ],
)
def test_citation_validator_rejects_noncanonical_answer_citations(
    citation_like: str,
) -> None:
    generated = GeneratedAnswer(
        answer=f"Answer {citation_like}",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^citation references must use canonical format$",
    ):
        CitationValidator().validate(generated, [make_evidence()])


def test_citation_validator_requires_answer_references_to_be_declared_by_claims() -> None:
    generated = GeneratedAnswer(
        answer="Answer [2]",
        claims=(GeneratedClaim(text="Claim", citation_refs=("[1]",)),),
    )

    with pytest.raises(
        CitationValidationError,
        match=r"^answer citation references must be declared by claims$",
    ):
        CitationValidator().validate(
            generated,
            [make_evidence(), make_evidence("[2]", "chk2")],
        )
