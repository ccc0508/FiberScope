# Langfuse tracing

The CLI and local website share `scripts/run_literature_agent.py`. New runs optionally project live checkpoints to Langfuse while preserving local JSON/SQLite as the primary records. No model, tool budget or answer prompt is changed.

Install with `.venv\Scripts\python.exe -m pip install -r backend/requirements-observability.txt`.
Create the Git-ignored `backend/.env.langfuse`:

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Set ENABLED to false to disable; missing config/SDK also disables tracing without breaking answers. Environment variables override the file. Never commit the real keys.

Run questions normally with `--architecture specialists`. The run folder `.rag-data/agent-runs/<run_id>/langfuse.json` contains the trace URL. In Langfuse, open Traces and select `FiberScope question`; root metadata contains the local run_id and pipeline version. Inspect generations for input messages, outputs and token usage; tool nodes contain requests and raw results. Specialist metadata includes coverage checks and delivery summaries, and generation inputs show the actual projected evidence seen by the model. Image binary content is omitted. Tool subprocesses receive the trace ID and parent tool span ID explicitly; internal retrieval and SQL stages attach to that tool on the same trace. No keys are passed in the tool request.

The projection deduplicates generation/tool nodes across checkpoints. Model/tool boundaries are checkpoint-observed. Child agents record monotonic duration and wall-clock end timestamps at their own completion (including result validation and evidence transfer), before parent synthesis. Failures also close the active child. Internal stages record monotonic duration, start/end timestamps, status, and error type; remote export overhead is excluded from measured internal stage duration. Tool wrapper duration includes subprocess startup and telemetry flush, so it can exceed the sum of internal stages. Observations are uploaded when ended; this is not token streaming. An abrupt process kill may leave partial or missing cloud records; local checkpoints remain useful.

Prompts, answers and evidence are sent to the configured project. Common secret fields/key patterns and image data URIs are redacted; this is not a general-purpose confidential-text classifier. Provider usage is recorded when returned; absent usage is unknown. Costs are not asserted as actual provider billing. Langfuse may show its own model-price estimates.

Telemetry exceptions do not fail the answer. Final flush is bounded to five seconds. SDK export failures can still mean missing cloud data; a local URL alone is not proof of ingestion. Existing historical traces and Jev/calibrated scores are not automatically imported in this phase. No server deployment is included.

Verification (2026-11-09): 23 observer/coordinator tests passed; dependency check clean. Auth check passed. A synthetic coordinator run with mocked model and tool produced a root, literature agent, four generations and a read_section tool; cloud readback returned HTTP 200 with all seven observations. No paid answering model was called.


## Internal steps (2026-11-09)

Retrieval: embedding → vector search (including configured table/image candidate adapters) → score filtering/deduplication → metadata fetch → reranking when enabled → seed selection → section/table context assembly → image association when enabled. Nodes carry candidate/selected chunk IDs, score information and assembly diagnostics, permitting comparison of where evidence disappeared. Image pixels/embedding vectors are not exported.

SQL: input/AST validation → connection → read-only transaction setup → EXPLAIN (without ANALYZE) → cursor execution → fetch → bounded result processing → output column metadata. Directory requests use a describe stage. PostgreSQL server cursors may perform work during fetch; examine execution plus fetch rather than treating cursor.execute duration as the entire query cost.

Internal stage records also persist in `.rag-data/tool-traces.sqlite3` under each tool record's `internal_steps`, including failed stages. They are not added to the model's tool payload. Cloud outages or killed workers may leave incomplete remote spans; these are not fabricated as successful stages. Internal tool stages appear after completion, not as a token stream.


Verification for internal tracing: 154 tests passed across observer/coordinator, retrieval, tools, SQL, rerank, context and visual evidence. An actual read-only PostgreSQL COUNT and one actual Qwen/retrieval/reranker call completed; decision/answer models were mocked (no answering-model charge). Cloud readback returned HTTP 200 and confirmed internal nodes share the tool parent, and child-agent end precedes parent synthesis. Seed-selection instrumentation was added after this smoke and covered by tests, not a second paid retrieval. These runs do not measure answer quality.
