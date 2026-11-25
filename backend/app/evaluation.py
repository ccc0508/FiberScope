"""Private benchmark API and one durable evaluation queue per installation."""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from secrets import compare_digest
from threading import Event, Lock, Thread
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field

from .agent_answer import run_agent_answer
from .evaluation_catalog import (
    GROUPS, ROOT, Suite, cases, database_snapshot, fingerprint, holdout_cases, read_json, runtime_manifest, runtime_matches,
)
from .literature import LiteratureSettings
from literature_rag.application.tools import encode

ACTIVE = {"queued", "answering", "scoring"}
MAX_CONCURRENT_CASES = 7
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def deepseek_usage(answer):
    total = 0
    incomplete = False
    for call in answer.get("model_calls", []):
        model = call.get("model") or answer.get("model") or ""
        if "deepseek" not in model.lower():
            continue
        usage = call.get("usage") or {}
        tokens = usage.get("total_tokens")
        if type(tokens) is not int or tokens < 0:
            incomplete = True
        else:
            total += tokens
    return total, incomplete


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=70)


class RunSelection(Selection):
    suite: Suite = "regression"


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=4000)


class EvaluationQueue:
    def __init__(self, config, path=None, *, answer=run_agent_answer, snapshot=database_snapshot):
        self.config = config
        self.path = path or config.root / "evaluation.sqlite3"
        self.lock = FileLock(str(self.path.with_suffix(".lock")), thread_local=False)
        self.answer = answer
        self.snapshot = snapshot
        self.snapshot_lock = Lock()
        self.wake = Event()
        self.stop = Event()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, parent TEXT,
                    manifest TEXT NOT NULL, snapshot TEXT
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    batch TEXT NOT NULL REFERENCES batches(id), id TEXT NOT NULL, position INTEGER NOT NULL,
                    spec TEXT NOT NULL, status TEXT NOT NULL, run_id TEXT, error TEXT,
                    duration_ms INTEGER, answer TEXT, grade TEXT,
                    deepseek_tokens INTEGER NOT NULL DEFAULT 0, deepseek_usage_incomplete INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(batch,id)
                );
                CREATE TABLE IF NOT EXISTS calibrations (
                    batch TEXT NOT NULL, id TEXT NOT NULL, timestamp TEXT NOT NULL,
                    score REAL NOT NULL, reason TEXT NOT NULL,
                    FOREIGN KEY(batch,id) REFERENCES evaluations(batch,id)
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            if "suite" not in {row["name"] for row in db.execute("PRAGMA table_info(batches)")}:
                db.execute("ALTER TABLE batches ADD COLUMN suite TEXT NOT NULL DEFAULT 'regression'")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(evaluations)")}
            if "deepseek_tokens" not in columns:
                db.execute("ALTER TABLE evaluations ADD COLUMN deepseek_tokens INTEGER NOT NULL DEFAULT 0")
                db.execute("ALTER TABLE evaluations ADD COLUMN deepseek_usage_incomplete INTEGER NOT NULL DEFAULT 0")
                # Rescoring copies the parent's answer and run ID without calling DeepSeek again.
                original_answers = db.execute("""SELECT e.batch, e.id, e.answer FROM evaluations e
                    JOIN batches b ON b.id=e.batch WHERE e.answer IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM evaluations p WHERE p.batch=b.parent AND p.id=e.id AND p.run_id=e.run_id
                    )""")
                db.executemany("""UPDATE evaluations SET deepseek_tokens=?, deepseek_usage_incomplete=?
                    WHERE batch=? AND id=?""",
                    ((*deepseek_usage(json.loads(row["answer"])), row["batch"], row["id"]) for row in original_answers))

    def start(self):
        if self.config.engine != "agent" or not self.config.enabled:
            return
        self.initialize()
        self.thread = Thread(target=self.work, daemon=True, name="evaluation-worker")
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=1)

    def create(self, selected, *, suite="regression", parent=None, copied=None, snapshot=None):
        batch = uuid4().hex
        manifest = runtime_manifest(self.config)
        manifest["cases_hash"] = fingerprint(selected)
        with self.db() as db:
            db.execute("INSERT INTO batches(id,created_at,parent,manifest,snapshot,suite) VALUES(?,?,?,?,?,?)",
                       (batch, now(), parent, encode(manifest), snapshot, suite))
            db.executemany(
                "INSERT INTO evaluations(batch,id,position,spec,status,run_id,duration_ms,answer) VALUES(?,?,?,?,?,?,?,?)",
                ((batch, case["id"], i, encode(case), "queued", previous["run_id"] if previous else None,
                  previous["duration_ms"] if previous else None, previous["answer"] if previous else None)
                 for i, case in enumerate(selected) for previous in [(copied or {}).get(case["id"])]),
            )
        self.wake.set()
        return batch

    def case_rows(self, db, batch, *, full=False, key=None):
        fields = "e.*" if full else """e.id, e.status, e.error, e.run_id, e.duration_ms,
            json_extract(e.spec, '$.group') AS group_name, json_extract(e.spec, '$.category') AS category,
            json_extract(e.grade, '$.score') AS original_score, json_extract(e.grade, '$.metrics') AS metrics_json"""
        return db.execute(f"""SELECT {fields}, c.score AS calibrated_score FROM evaluations e
            LEFT JOIN calibrations c ON c.rowid=(SELECT max(rowid) FROM calibrations
                WHERE batch=e.batch AND id=e.id) WHERE e.batch=? AND (? IS NULL OR e.id=?)
                ORDER BY position""", (batch, key, key)).fetchall()

    def batch(self, db, batch):
        row = db.execute("SELECT * FROM batches WHERE id=?", (batch,)).fetchone()
        if row is None:
            raise HTTPException(404, "评测批次不存在。")
        return row

    def summary(self, row):
        if "spec" in row.keys():
            spec = json.loads(row["spec"])
            grade = json.loads(row["grade"]) if row["grade"] else {}
        else:
            spec = dict(group=row["group_name"], category=row["category"])
            grade = dict(score=row["original_score"], metrics=json.loads(row["metrics_json"] or "{}"))
        return dict(id=row["id"], group=spec["group"], category=spec["category"],
                    status=row["status"], error=row["error"], duration_ms=row["duration_ms"], run_id=row["run_id"],
                    score=grade.get("score"), calibrated_score=row["calibrated_score"], metrics=grade.get("metrics", {}))

    def detail(self, batch):
        with self.db() as db:
            run = self.batch(db, batch)
            rows = self.case_rows(db, batch)
            usage = db.execute("""SELECT COALESCE(SUM(deepseek_tokens), 0) AS total_tokens,
                MAX(deepseek_usage_incomplete OR
                    (status IN ('answer_failed','interrupted') AND run_id IS NOT NULL AND answer IS NULL)
                ) AS incomplete FROM evaluations WHERE batch=?""", (batch,)).fetchone()
            origin = run
            while origin["parent"]:
                reused = db.execute("""SELECT 1 FROM evaluations child JOIN evaluations parent
                    ON parent.batch=? AND parent.id=child.id AND parent.run_id=child.run_id
                    WHERE child.batch=? LIMIT 1""", (origin["parent"], origin["id"])).fetchone()
                if not reused:
                    break
                origin = self.batch(db, origin["parent"])
        snapshot = json.loads(run["snapshot"]) if run["snapshot"] else {}
        manifest = json.loads(origin["manifest"])
        scoring_manifest = json.loads(run["manifest"])
        manifest["cases_hash"] = scoring_manifest.get("cases_hash")
        return dict(id=run["id"], created_at=run["created_at"], parent=run["parent"], suite=run["suite"],
                    manifest=manifest, scoring_manifest=scoring_manifest,
                    database_fingerprint=snapshot.get("fingerprint"),
                    deepseek_usage=dict(total_tokens=usage["total_tokens"], incomplete=bool(usage["incomplete"])),
                    cases=[self.summary(row) for row in rows])

    def detail_case(self, batch, key):
        with self.db() as db:
            run = self.batch(db, batch)
            row = next(iter(self.case_rows(db, batch, full=True, key=key)), None)
            if row is None:
                raise HTTPException(404, "本轮未运行该题。")
            reviews = db.execute("SELECT timestamp,score,reason FROM calibrations WHERE batch=? AND id=? ORDER BY rowid",
                                 (batch, key)).fetchall()
        spec = json.loads(row["spec"])
        snapshot = json.loads(run["snapshot"]) if run["snapshot"] else {}
        private = run["suite"] == "holdout"
        return dict(**self.summary(row), question=spec["question"], reference={} if private else spec["reference"],
                    reference_results=[] if private else snapshot.get("references", {}).get(key, []),
                    answer=json.loads(row["answer"]) if row["answer"] else None,
                    grade=json.loads(row["grade"]) if row["grade"] else None, calibrations=[dict(x) for x in reviews])

    def rerun(self, batch, mode, ids=None):
        with self.db() as db:
            parent = self.batch(db, batch)
            rows = self.case_rows(db, batch, full=True)
        if any(row["status"] in ACTIVE for row in rows):
            raise HTTPException(409, "本轮还在执行。")
        if mode == "rescore":
            rows = [row for row in rows if row["answer"] and json.loads(row["answer"])["status"] == "completed"
                    and (ids is None or row["id"] in ids)]
        else:
            rows = [row for row in rows if row["status"] in {"answer_failed", "interrupted", "setup_failed"}
                    and (not row["answer"] or json.loads(row["answer"])["status"] != "completed")]
        if not rows:
            raise HTTPException(422, "没有符合条件的题目。")
        return self.create([json.loads(row["spec"]) for row in rows], suite=parent["suite"], parent=batch,
                           copied={row["id"]: row for row in rows} if mode == "rescore" else None,
                           snapshot=parent["snapshot"] if mode == "rescore" else None)

    def update(self, row, **values):
        assignments = ", ".join(field + "=?" for field in values)
        with self.db() as db:
            db.execute(f"UPDATE evaluations SET {assignments} WHERE batch=? AND id=?",
                       (*values.values(), row["batch"], row["id"]))

    def work(self):
        while not self.stop.is_set():
            try:
                self.lock.acquire(timeout=0)
                break
            except Timeout:
                self.stop.wait(.5)
        else:
            return
        running = {}
        try:
            with self.db() as db:
                db.execute("UPDATE evaluations SET status='interrupted', error='工作进程重启，请按需补跑。' "
                           "WHERE status IN ('answering','scoring')")
            while not self.stop.is_set():
                self.wake.clear()
                running = {key: work for key, work in running.items() if not work[1].is_set()}
                if len(running) < MAX_CONCURRENT_CASES:
                    with self.db() as db:
                        rows = db.execute("""SELECT e.*, b.manifest, b.snapshot FROM evaluations e
                            JOIN batches b ON b.id=e.batch WHERE e.status='queued'
                            ORDER BY b.created_at,e.position LIMIT ?""", (MAX_CONCURRENT_CASES,)).fetchall()
                    for row in rows:
                        if self.stop.is_set() or len(running) == MAX_CONCURRENT_CASES:
                            break
                        key = (row["batch"], row["id"])
                        if key not in running:
                            done = Event()
                            thread = Thread(target=self.run_work_item, args=(row, done),
                                            daemon=True, name="evaluation-case")
                            thread.start()
                            running[key] = (thread, done)
                self.wake.wait(2)
        finally:
            for thread, _ in running.values():
                thread.join()
            self.lock.release()

    def run_work_item(self, row, done):
        try:
            self.run_case(row)
        except Exception as error:
            logger.error("Evaluation case %s/%s failed: %s", row["batch"], row["id"], type(error).__name__)
            self.update(row, status="interrupted", error=type(error).__name__)
        finally:
            done.set()
            self.wake.set()

    def prepare_snapshot(self, batch):
        with self.snapshot_lock:
            with self.db() as db:
                saved = self.batch(db, batch)["snapshot"]
                if saved:
                    return json.loads(saved)
                selected = [json.loads(item["spec"]) for item in
                            db.execute("SELECT spec FROM evaluations WHERE batch=? ORDER BY position", (batch,))]
            snapshot = self.snapshot(selected)
            with self.db() as db:
                db.execute("UPDATE batches SET snapshot=? WHERE id=?", (encode(snapshot), batch))
            return snapshot

    def run_case(self, row):
        try:
            config = self.config
            spec = json.loads(row["spec"])
            frozen = json.loads(row["manifest"])
            manifest = runtime_manifest(config)
            if not runtime_matches(frozen, manifest):
                raise ValueError("Agent 或文献索引发生变化。请新建评测。")
            snapshot = json.loads(row["snapshot"]) if row["snapshot"] else None
            if spec["group"] in {"sql", "mixed"} and not row["answer"]:
                if snapshot is None:
                    snapshot = self.prepare_snapshot(row["batch"])
                if self.snapshot([])["fingerprint"] != snapshot["fingerprint"]:
                    raise ValueError("实验数据已变化。请新建评测。")
        except Exception as error:
            self.update(row, status="setup_failed", error=str(error) if isinstance(error, ValueError) else type(error).__name__)
            return

        if row["answer"]:
            result = json.loads(row["answer"])
        else:
            run_id = "eval-" + uuid4().hex
            self.update(row, status="answering", run_id=run_id)
            start = perf_counter()
            try:
                with self.trace(run_id, row["id"]):
                    record = self.answer(config, spec["prompt"], run_id=run_id)
                result = dict(record["agent_run"], evidence=record["agent_evidence"],
                              tool_trace=record["agent_tool_trace"])
                link = ROOT / ".rag-data/agent-runs" / run_id / "langfuse.json"
                try:
                    if link.is_file():
                        result["langfuse"] = read_json(link)
                except (OSError, ValueError):
                    pass
                result.update(case_id=spec["id"], end_to_end_ms=round((perf_counter() - start) * 1000))
                if spec["group"] in {"sql", "mixed"}:
                    result["database_verified"] = False
                complete = result["status"] == "completed" and bool(result["answer"].strip())
                tokens, incomplete = deepseek_usage(result)
                self.update(row, answer=encode(result), duration_ms=result["end_to_end_ms"],
                            deepseek_tokens=tokens, deepseek_usage_incomplete=incomplete,
                            status="scoring" if complete else "answer_failed",
                            error=None if complete else (result.get("stop_reason") or "Agent 未完成"))
                if not complete:
                    return
            except Exception as error:
                self.update(row, status="answer_failed", error=type(error).__name__,
                            duration_ms=round((perf_counter() - start) * 1000))
                return
        self.update(row, status="scoring")
        grading_started = perf_counter()
        try:
            if result.get("database_verified") is False:
                if self.snapshot([])["fingerprint"] != snapshot["fingerprint"]:
                    result.update(status="failed", stop_reason="database_changed_during_run")
                    self.update(row, status="answer_failed", error=result["stop_reason"], answer=encode(result))
                    return
                result["database_verified"] = True
                self.update(row, answer=encode(result))
            references = (snapshot or {}).get("references", {}).get(spec["id"], [])
            scored = self.grade(spec, result, references)
            if "error" in scored:
                self.update(row, status="score_failed", error=scored["error"])
            else:
                scored["duration_ms"] = round((perf_counter() - grading_started) * 1000)
                self.update(row, status="scored", grade=encode(scored), error=None)
        except Exception as error:
            self.update(row, status="score_failed", error=type(error).__name__)

    @staticmethod
    @contextmanager
    def trace(run_id, case_id):
        from .qa_tracing import step
        with step("evaluation.answer", run_id=run_id, case_id=case_id):
            yield

    def grade(self, spec, result, references):
        packet = {"case": spec, "result": result, "library": str(self.config.library_root), "references": references}
        completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/evaluation_web_grade.py")],
                                   cwd=ROOT, input=encode(packet), capture_output=True, text=True,
                                   encoding="utf-8", timeout=620, check=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(completed.stdout)


def router(config=None, admin_token=None):
    config = config or LiteratureSettings()
    from dotenv import dotenv_values

    options = dotenv_values(ROOT / "backend/.env", interpolate=False)
    holdout_dir = os.environ.get("FIBERSCOPE_HOLDOUT_DIR", options.get("FIBERSCOPE_HOLDOUT_DIR")) or ""
    if admin_token is None:
        admin_token = os.environ.get("FIBERSCOPE_EVALUATION_TOKEN", options.get("FIBERSCOPE_EVALUATION_TOKEN", ""))
    queue = EvaluationQueue(config)

    def catalog_cases(suite):
        if suite == "regression":
            return list(cases())
        if not holdout_dir:
            raise HTTPException(404, "此部署未配置 Holdout 题库。")
        try:
            return list(holdout_cases(Path(holdout_dir)))
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, "Holdout 题库不可用或未通过封存校验。") from None

    def authorize(request: Request):
        if not admin_token or not config.enabled or config.engine != "agent":
            raise HTTPException(404, "评测工作台未启用。")
        authorization = request.headers.get("Authorization", "")
        if not compare_digest(authorization.encode(), ("Bearer " + admin_token).encode()):
            raise HTTPException(401, "请输入评测工作台访问令牌。")

    @asynccontextmanager
    async def lifespan(_):
        if admin_token:
            queue.start()
        try:
            yield
        finally:
            queue.close()

    routes = APIRouter(prefix="/api/v1/evaluation", dependencies=[Depends(authorize)], lifespan=lifespan)

    @routes.get("/cases")
    def catalog(suite: Suite = "regression"):
        return dict(groups=GROUPS, suite=suite, available_suites=["regression", "holdout"] if holdout_dir else ["regression"],
                    cases=[{k: case[k] for k in ("id", "group", "category", "question")} for case in catalog_cases(suite)],
                    manifest=runtime_manifest(config), max_concurrent_cases=MAX_CONCURRENT_CASES)

    @routes.post("/runs", status_code=202)
    def create(selection: RunSelection):
        judge_key = os.environ.get("QA_JEV_API_KEY", dotenv_values(ROOT / "backend/.env.jev").get("QA_JEV_API_KEY", ""))
        if not (judge_key or "").strip():
            raise HTTPException(503, "服务端尚未配置 Jev 评分密钥。")
        pool = catalog_cases(selection.suite)
        keys = set(selection.ids)
        if len(keys) != len(selection.ids) or not keys <= {case["id"] for case in pool}:
            raise HTTPException(422, "题目编号不存在或重复。")
        return {"id": queue.create([case for case in pool if case["id"] in keys], suite=selection.suite)}

    @routes.get("/runs")
    def listing(suite: Suite = "regression"):
        with queue.db() as db:
            ids = [row["id"] for row in db.execute(
                "SELECT id FROM batches WHERE suite=? ORDER BY created_at DESC LIMIT 100", (suite,),
            )]
        return {"runs": [queue.detail(key) for key in ids]}

    @routes.get("/runs/{batch}")
    def get_run(batch: str):
        return queue.detail(batch)

    @routes.get("/runs/{batch}/cases/{key}")
    def get_result(batch: str, key: str):
        return queue.detail_case(batch, key)

    @routes.post("/runs/{batch}/retry", status_code=202)
    def retry(batch: str):
        return {"id": queue.rerun(batch, "retry")}

    @routes.post("/runs/{batch}/rescore", status_code=202)
    def rescore(batch: str, selection: Selection):
        return {"id": queue.rerun(batch, "rescore", set(selection.ids))}

    @routes.post("/runs/{batch}/cases/{key}/calibration")
    def calibrate(batch: str, key: str, body: Calibration):
        with queue.db() as db:
            row = db.execute("SELECT status FROM evaluations WHERE batch=? AND id=?", (batch, key)).fetchone()
            if not row or row["status"] != "scored":
                raise HTTPException(422, "评分完成后才可校准。")
            db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?)", (batch, key, now(), body.score, body.reason))
        return queue.detail_case(batch, key)

    return routes
