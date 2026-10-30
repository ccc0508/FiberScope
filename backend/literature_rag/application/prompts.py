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

ANSWER_GUIDANCE_VERSION = 'answer-completeness-v2'
ANSWER_GUIDANCE = """Answer each requested part directly and briefly. Put all substantive content in claims.
Omit related background, repeated conclusions and unrequested detail.
Keep claims short. Split independently supported facts when they need different sources; for conflicting
values, cite each value separately before stating the conflict.
Attach the smallest sufficient reference set. Every attached reference must directly support a substantive
component of that claim; together they must cover the whole claim. Topical similarity is insufficient.
Include the sample, value, unit and conditions needed for the requested comparison. Use one numerical
example or counterexample only when relevant and available; never estimate missing data.
Preserve the authors' uncertainty. State necessary interpretation limits when justified by the evidence;
do not turn association into established causation or a conversion formula, or invent generic caveats.
Answer supported parts first. Bound missing information to the supplied excerpts unless wider absence is
established. Explain what the cited excerpts actually report; do not use topical citations as proof of absence.
Do not reconstruct raw measurements from summaries. Return only the existing answer/claims structure."""


def system_prompt(guidance_enabled: bool = False) -> str:
    if type(guidance_enabled) is not bool:
        raise ValueError('answer guidance flag must be boolean')
    return SYSTEM_PROMPT+'\n\n'+ANSWER_GUIDANCE if guidance_enabled else SYSTEM_PROMPT


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
