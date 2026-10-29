# Reused literature core

Source: the user's existing `D:\develop\srp` repository, commit
`887c2e465f3b8ded9d92927cf2523d53516fc99f`.

This snapshot includes only configuration, domain models, protocols, retrieval,
answer generation, citation validation, and the SQLite/Chroma/OpenAI/DeepSeek adapters.
The old CLI, Streamlit dashboard, experimental SQLite query engine, modeling and
experimental data importer are not included.

The web integration is in `app/literature.py` and `literature_worker.py`.
The worker overrides metadata access with a read-only SQLite connection and never
calls the metadata initialization or write methods. Answers are rendered from the
validated claims, never from the unchecked model answer field. Inherited core tests
are kept in `tests/test_literature_answers.py`, `test_literature_retrieval.py` and
`test_literature_citations.py`, with renamed test fakes to avoid collisions.

Local papers, index files and model credentials are excluded from Git.

The history integration extends this snapshot with explicit refusal reason codes,
allowlisted configuration fingerprints, and provider-reported token usage. It does
not change the single retrieval pass or citation validation rules. Stored feedback
is user feedback, not a ground-truth label or a semantic correctness evaluation.

The first context improvement adds optional same-page neighbor expansion, exact legacy
overlap removal, complete table units, character budgets and source-chunk snapshots.
`scripts/reindex_literature_structure.py` builds a separate version from existing extracted
text; it does not overwrite the old index. `LITERATURE_LIBRARY_DIR` selects that library
while history and extraction records keep their existing data root. Core defaults leave
expansion disabled for legacy runs; the example configuration opts in. See
`docs/QA_CONTEXT_V1_20261029.md` for validation and scope limits.
