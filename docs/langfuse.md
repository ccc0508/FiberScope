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

Run questions normally with `--architecture specialists`. The run folder `.rag-data/agent-runs/<run_id>/langfuse.json` contains the trace URL. In Langfuse, open Traces and select `FiberScope question`; root metadata contains the local run_id and pipeline version. Inspect generations for input messages, outputs and token usage; tool nodes contain requests and raw results. Specialist metadata includes coverage checks and delivery summaries, and generation inputs show the actual projected evidence seen by the model. Image binary content is omitted. Tool subprocesses are represented by spans in the calling coordinator, not automatically instrumented internally.

The projection deduplicates generation/tool nodes across checkpoints. Durations reflect checkpoint-observed boundaries; child agent spans currently close at question completion, so do not interpret child duration as exact active execution time. Observations are uploaded when ended; this is not token streaming. An abrupt process kill may leave partial or missing cloud records; local checkpoints remain useful.

Prompts, answers and evidence are sent to the configured project. Common secret fields/key patterns and image data URIs are redacted; this is not a general-purpose confidential-text classifier. Provider usage is recorded when returned; absent usage is unknown. Costs are not asserted as actual provider billing. Langfuse may show its own model-price estimates.

Telemetry exceptions do not fail the answer. Final flush is bounded to five seconds. SDK export failures can still mean missing cloud data; a local URL alone is not proof of ingestion. Existing historical traces and Jev/calibrated scores are not automatically imported in this phase. No server deployment is included.

Verification (2026-11-09): 23 observer/coordinator tests passed; dependency check clean. Auth check passed. A synthetic coordinator run with mocked model and tool produced a root, literature agent, four generations and a read_section tool; cloud readback returned HTTP 200 with all seven observations. No paid answering model was called.
