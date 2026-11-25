"""Versioned benchmark inputs and read-only reference snapshots."""

import hashlib
import json
import os
import sqlite3
import subprocess
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from psycopg import sql
from sqlglot import parse_one

from .experiment_sql import ALLOWED, connect, validate_sql
from literature_rag.application.tools import encode

ROOT = Path(__file__).resolve().parents[2]
PAPERS = ROOT / "fiberscope-eval-8papers-v1"
SQL = ROOT / "data/text-to-sql-evaluation/cases-v1.json"
MIXED = ROOT / "data/mixed-agent-evaluation"
GROUPS = {"literature": "文献题", "sql": "SQL 题", "mixed": "综合题", "non_paper": "日常题"}
Suite = Literal["regression", "holdout"]
RUBRICS = {"literature": "FS8-rubric-v2-20261106", "sql": "sql-web-v1",
           "mixed": "mixed-v1", "non_paper": "daily-web-v1"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(data):
    return hashlib.sha256(encode(data).encode()).hexdigest()


def chroma_sqlite_fingerprint(path):
    """Hash a consistent snapshot of the index, excluding Chroma's startup lock table."""
    digest = hashlib.sha256()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.execute("BEGIN")
        schema = db.execute("""
            SELECT type, name, tbl_name, sql FROM sqlite_schema
            WHERE tbl_name <> 'acquire_write' AND substr(name, 1, 7) <> 'sqlite_'
            ORDER BY type, name
        """).fetchall()
        digest.update(encode(schema).encode("utf-8"))
        for kind, name, _, _ in schema:
            if kind != "table":
                continue
            identifier = '"' + name.replace('"', '""') + '"'
            columns = db.execute(f"SELECT * FROM {identifier} LIMIT 0").description
            order = ", ".join(str(index) for index in range(1, len(columns) + 1))
            digest.update(encode(name).encode("utf-8"))
            for row in db.execute(f"SELECT * FROM {identifier} ORDER BY {order}"):
                digest.update(repr(row).encode("utf-8"))
                digest.update(b"\n")
    return digest.hexdigest()


def cases():
    questions = {row["id"]: row for row in map(json.loads, (PAPERS / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines())}
    for gold in map(json.loads, (PAPERS / "gold.jsonl").read_text(encoding="utf-8-sig").splitlines()):
        group = "non_paper" if gold["group"] == "no_paper" else "literature"
        prompt = (PAPERS / "tasks" / (gold["id"] + ".md")).read_text(encoding="utf-8-sig")
        yield dict(id=gold["id"], group=group, category=gold["group"],
                   question=questions[gold["id"]]["question"], prompt=prompt, reference=gold)
    for group, path in [("sql", SQL), ("mixed", MIXED / "cases-v1.json")]:
        for row in read_json(path):
            yield dict(id=row["id"], group=group, category=row["category"], question=row["question"],
                       prompt=row["question"], reference=row)


def holdout_cases(root):
    manifest = read_json(root / "manifest.json")

    def frozen(relative):
        raw = (root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"][relative]:
            raise ValueError("Holdout file does not match the sealed manifest.")
        return raw.decode("utf-8-sig")

    if manifest["version"] != "fiberscope-holdout-v1":
        raise ValueError("Unsupported Holdout version.")
    questions = [json.loads(line) for line in frozen("answer-input/questions.jsonl").splitlines() if line.strip()]
    gold = {row["id"]: row for row in map(json.loads, frozen("review-only/gold.jsonl").splitlines())}
    rubric = json.loads(frozen("review-only/rubric.json"))
    sources = {item["document_id"]: item for item in
               json.loads(frozen("review-only/sources.json"))["source_documents"]}
    expected = {"literature": 14, "sql": 10, "mixed": 12, "non_paper": 4}
    if (len(questions) != 40 or len(gold) != 40 or {row["id"] for row in questions} != gold.keys()
            or Counter(row["group"] for row in gold.values()) != expected or rubric["version"] != manifest["version"]):
        raise ValueError("Invalid Holdout case catalog.")
    for row in questions:
        reference = gold[row["id"]]
        group = reference["group"]
        yield dict(id=row["id"], group=group, category=reference["topic"], question=row["question"],
                   prompt=row["question"], reference=reference, holdout=dict(
                       version=manifest["version"], fingerprint=fingerprint(manifest),
                       rubric=dict(**rubric["scales"][group], rules=rubric["rules"]),
                       sources={key: sources[key] for key in
                                dict.fromkeys(item["document_id"] for item in reference["literature_evidence"])},
                   ))


def runtime_manifest(config):
    env = dotenv_values(ROOT / "backend/.env.literature", interpolate=False)
    keys = ("RAG_LLM_PROVIDER", "RAG_LLM_MODEL", "RAG_LLM_THINKING_ENABLED", "RAG_LLM_REASONING_EFFORT",
            "RAG_EMBEDDING_PROVIDER", "RAG_EMBEDDING_MODEL", "RAG_EMBEDDING_DIMENSIONS", "RAG_RERANK_PROVIDER",
            "RAG_RERANK_MODEL", "RAG_RERANK_ENABLED", "RAG_QUERY_REWRITE_ENABLED", "RAG_TOP_K", "RAG_MIN_SCORE",
            "RAG_CONTEXT_EXPANSION_ENABLED", "RAG_CONTEXT_EXPANSION_STRATEGY", "RAG_CONTEXT_NEIGHBOR_RADIUS",
            "RAG_CONTEXT_MAX_EVIDENCE_CHARS", "RAG_CONTEXT_MAX_TOTAL_CHARS", "RAG_TABLE_RETRIEVAL_ENABLED",
            "RAG_VISUAL_RETRIEVAL_ENABLED", "RAG_VISUAL_MAX_IMAGES", "RAG_VISUAL_MAX_TOTAL_BYTES")
    config_values = {key: os.environ.get(key, env.get(key)) for key in keys}
    digest = hashlib.sha256()
    runtime_paths = [ROOT / "scripts/run_literature_agent.py", *sorted((ROOT / "backend/literature_rag").rglob("*.py")),
                     *sorted((ROOT / "backend/app").glob("*.py")), ROOT / "backend/literature_worker.py",
                     ROOT / "scripts/evaluation_web_grade.py", ROOT / "scripts/grade_agent_eightpapers_20261105.py",
                     PAPERS / "rubric.json", PAPERS / "sources.json", MIXED / "rubric-v1.json"]
    for path in runtime_paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    library = {}
    root = config.library_root
    index = root / "chroma"
    vector_files = sorted(path for path in index.rglob("*") if path.suffix in {".bin", ".pickle", ".sqlite3"})
    for path in (root / "metadata.sqlite3", root / "structure.json", *vector_files):
        if path.is_file():
            if path == index / "chroma.sqlite3":
                library[path.relative_to(root).as_posix()] = chroma_sqlite_fingerprint(path)
                continue
            with path.open("rb") as handle:
                library[path.relative_to(root).as_posix()] = hashlib.file_digest(handle, "sha256").hexdigest()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    specialists = config.agent_architecture == "specialists"
    return dict(commit=commit, runtime_hash=digest.hexdigest(), configuration=config_values, architecture=config.agent_architecture,
                library=library, rubrics=RUBRICS, judge="typesafe/jev-1.14",
                budget=dict(models=20 if specialists else 10, tools=12 if specialists else 8,
                            seconds=min(360 if specialists else 240, config.timeout_seconds - 10)))


def runtime_matches(frozen, current):
    changed = {key for key, value in current.items() if frozen.get(key) != value}
    if not changed:
        return True
    if changed - {"commit", "runtime_hash"}:
        return False
    # Only allow specific scheduler upgrades between exact runtime fingerprints.
    upgrades = read_json(ROOT / "backend/app/evaluation_runtime_upgrades.json")
    return frozen.get("runtime_hash") in upgrades.get(current.get("runtime_hash"), ())


def database_snapshot(selected):
    """Capture data provenance and reference queries in the same read-only transaction."""
    with connect() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        fingerprints = {}
        for view in sorted(ALLOWED):
            rows = db.execute(sql.SQL("SELECT * FROM fiber.{}").format(sql.Identifier(view))).fetchall()
            fingerprints[view] = dict(count=len(rows), hash=fingerprint(sorted(rows, key=repr)))
        references = {}
        for case in selected:
            outputs = []
            gold = case["reference"]
            frozen = gold.get("sql_references", []) if "holdout" in case else None
            statements = [item["sql"] for item in frozen] if frozen is not None else gold.get("reference_sql", [])
            for reference in statements:
                query, _ = validate_sql(reference)
                cur = db.execute(query)
                outputs.append(dict(sql=query, columns=[col.name for col in cur.description],
                                    rows=cur.fetchall(), ordered=bool(parse_one(query, read="postgres").args.get("order"))))
            if frozen is not None:
                for actual, expected in zip(outputs, frozen, strict=True):
                    rows = list(map(encode, actual["rows"]))
                    gold_rows = list(map(encode, expected["rows"]))
                    matches = rows == gold_rows if expected["ordered"] else Counter(rows) == Counter(gold_rows)
                    if not matches or actual["columns"] != expected["columns"]:
                        raise ValueError("实验数据与封存的 Holdout 参考结果不一致。")
            references[case["id"]] = outputs
    return dict(fingerprint=fingerprint(fingerprints), views=fingerprints, references=json.loads(encode(references)))
