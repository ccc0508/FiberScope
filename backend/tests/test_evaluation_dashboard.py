from collections import Counter
from json import dumps
from time import monotonic, sleep

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evaluation import EvaluationQueue, router
from app.evaluation_catalog import cases
from app.literature import LiteratureSettings


def wait_for(client, run):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        result = client.get(f"/api/v1/evaluation/runs/{run}").json()
        if result["cases"][0]["status"] == "scored":
            return result
        sleep(.02)
    raise AssertionError(result)


def test_private_evaluation_flow_can_rescore_without_regenerating(monkeypatch, tmp_path):
    prompts = []
    snapshots = []

    def answer(config, question, *, run_id):
        prompts.append(question)
        return {
            "agent_run": {"status": "completed", "answer": "saved candidate", "model": "deepseek-flash",
                          "model_calls": [{"usage": {"total_tokens": 120}}, {"usage": {"total_tokens": 80}},
                                          {"model": "typesafe/jev-1.14", "usage": {"total_tokens": 50}}],
                          "tool_calls": []},
            "agent_evidence": [], "agent_tool_trace": [],
        }

    def create_queue(self, config):
        original(self, config, answer=answer, snapshot=lambda selected: snapshots.append(selected))

    original = EvaluationQueue.__init__
    monkeypatch.setattr(EvaluationQueue, "__init__", create_queue)
    monkeypatch.setattr(EvaluationQueue, "grade", lambda self, *_: {"score": 80, "metrics": {}, "review": {}, "decisions": {}})
    monkeypatch.setenv("QA_JEV_API_KEY", "test-only-key")
    config = LiteratureSettings(enabled=True, data_dir=tmp_path)
    app = FastAPI()
    app.include_router(router(config, "test-eval-token"))

    with TestClient(app) as client:
        assert client.get("/api/v1/evaluation/cases").status_code == 401
        client.headers["Authorization"] = "Bearer test-eval-token"
        listing = client.get("/api/v1/evaluation/cases").json()
        assert Counter(c["group"] for c in listing["cases"]) == {"literature": 24, "sql": 20, "mixed": 20, "non_paper": 6}
        assert all("reference" not in case and "prompt" not in case for case in listing["cases"])
        assert client.post("/api/v1/evaluation/runs", json={"ids": ["missing"]}).status_code == 422
        result = client.post("/api/v1/evaluation/runs", json={"ids": ["FS8-025"]})
        assert result.status_code == 202
        run = result.json()["id"]
        saved = wait_for(client, run)
        assert saved["deepseek_usage"] == {"total_tokens": 200, "incomplete": False}
        case_url = f"/api/v1/evaluation/runs/{run}/cases/FS8-025"
        detail = client.get(case_url).json()
        assert detail["answer"]["answer"] == "saved candidate"
        assert detail["score"] == 80
        adjusted = client.post(case_url + "/calibration", json={"score": 90, "reason": "人工核对"}).json()
        assert adjusted["score"] == 80 and adjusted["calibrated_score"] == 90
        rescore = client.post(f"/api/v1/evaluation/runs/{run}/rescore", json={"ids": ["FS8-025"]})
        assert rescore.status_code == 202
        new_result = wait_for(client, rescore.json()["id"])
        assert new_result["parent"] == run
        assert new_result["cases"][0]["run_id"] == saved["cases"][0]["run_id"]
        assert new_result["deepseek_usage"] == {"total_tokens": 0, "incomplete": False}
        history = client.get("/api/v1/evaluation/runs").json()["runs"]
        assert {entry["id"]: entry["deepseek_usage"]["total_tokens"] for entry in history} == {
            run: 200, new_result["id"]: 0,
        }
    expected = next(case for case in cases() if case["id"] == "FS8-025")
    assert prompts == [expected["prompt"]]
    assert not snapshots


def test_migration_counts_failed_deepseek_calls_and_skips_reused_history(tmp_path):
    queue = EvaluationQueue(LiteratureSettings(data_dir=tmp_path))
    queue.initialize()
    spec = dumps({"group": "literature", "category": "single"})
    completed = dumps({"model": "deepseek-flash", "model_calls": [{"usage": {"total_tokens": 60}}]})
    failed = dumps({"model": "deepseek-flash", "model_calls": [{"usage": {"total_tokens": 40}}, {"usage": None}]})
    with queue.db() as db:
        db.execute("ALTER TABLE evaluations DROP COLUMN deepseek_tokens")
        db.execute("ALTER TABLE evaluations DROP COLUMN deepseek_usage_incomplete")
        db.executemany("INSERT INTO batches(id,created_at,parent,manifest) VALUES(?, 'date', ?, '{}')",
                       [("original", None), ("rescore", "original")])
        db.executemany("""INSERT INTO evaluations(batch,id,position,spec,status,run_id,answer)
            VALUES(?,?,0,?,?,?,?)""", [
            ("original", "done", spec, "scored", "kept-run", completed),
            ("original", "failed", spec, "answer_failed", "failed-run", failed),
            ("rescore", "done", spec, "scored", "kept-run", completed),
        ])

    queue.initialize()
    queue.initialize()

    assert queue.detail("original")["deepseek_usage"] == {"total_tokens": 100, "incomplete": True}
    assert queue.detail("rescore")["deepseek_usage"] == {"total_tokens": 0, "incomplete": False}
