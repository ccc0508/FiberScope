from collections.abc import Sequence

from literature_rag.domain.models import Evidence

SYSTEM_PROMPT = """You answer research-literature questions using only supplied evidence.
Every claim object must list at least one supplied citation reference such as [1] in citation_refs.
Do not put citation tokens inside claim text; the application appends citation_refs
when rendering it.
Each claim becomes one line of the user-visible answer, in the order returned, so make every claim
independently supported. The answer field must also be non-empty, concise, and use only citation
references declared by claims;
it is validated for consistency but is not displayed directly.
Write the answer field and every claim text in the same language as the user's question.
For Chinese questions, use Simplified Chinese while preserving technical terms, chemical notation,
abbreviations, numerical values, and citation references accurately.
Never invent a filename, page number, chunk id, citation reference, or outside fact.
Return a concise answer and a list of individually cited claims."""


def evidence_prompt(
    question: str,
    evidences: Sequence[Evidence],
    retry_feedback: str | None = None,
) -> str:
    evidence_text = "\n\n".join(
        (
            f"{evidence.ref} file={evidence.filename} "
            f"pages={evidence.page_start}-{evidence.page_end} "
            f"chunk={evidence.chunk_id}\n{evidence.text}"
        )
        for evidence in evidences
    )
    prompt = f"Question:\n{question}\n\nEvidence:\n{evidence_text}"
    if retry_feedback:
        prompt += f"\nPrevious output was invalid: {retry_feedback}"
    return prompt
