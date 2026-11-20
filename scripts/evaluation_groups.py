"""List the current four evaluation groups or summarize a complete frozen 70-case run."""
import argparse
import json
import math
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def groups():
    papers = ROOT / "fiberscope-eval-8papers-v1"
    labels = {r["id"]: r["group"] for r in json_lines(papers / "gold.jsonl")}
    cases = {"literature": [], "sql": [], "mixed": [], "non_paper": []}
    for row in json_lines(papers / "questions.jsonl"):
        group = {"single": "literature", "cross": "literature", "no_paper": "non_paper"}[labels[row["id"]]]
        cases[group].append(row)
    for group, folder in [("sql", "text-to-sql-evaluation"), ("mixed", "mixed-agent-evaluation")]:
        for row in load(ROOT / "data" / folder / "cases-v1.json"):
            cases[group].append({"id": row["id"], "question": row["question"]})
    ids = [row["id"] for rows in cases.values() for row in rows]
    if len(set(ids)) != 70 or list(map(len, cases.values())) != [24, 20, 20, 6]:
        raise ValueError("Unexpected four-group evaluation membership")
    return cases


def summarize(cases, directory):
    observed = {"tools": [], "elapsed_ms": [], "tokens": []}
    for case in cases:
        state = load(directory / (case["id"] + ".json"))
        if state.get("case_id") != case["id"]:
            raise ValueError(f"Case identity mismatch for {case['id']}")
        for name, value in [("tools", (state.get("budget_usage") or {}).get("tools")),
                            ("elapsed_ms", state.get("end_to_end_ms"))]:
            if value is not None:
                observed[name].append(value)
        calls = state.get("model_calls")
        if calls is not None:
            usage = [(c.get("usage") or {}).get("total_tokens") for c in calls]
            if all(value is not None for value in usage):
                observed["tokens"].append(sum(usage))
    result = {"cases": len(cases), "recorded": {k: len(v) for k, v in observed.items()}}
    for name, values in observed.items():
        result["mean_" + name] = round(mean(values), 2) if values else None
    times = sorted(observed["elapsed_ms"])
    result["p95_elapsed_ms"] = times[math.ceil(len(times) * .95) - 1] if times else None
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs=3, type=Path, metavar=("FS8", "SQL", "MIX"),
                        help="Three frozen result directories (the same one may be given three times).")
    args = parser.parse_args()
    output = groups()
    if args.runs:
        paper, sql, mixed = args.runs
        folders = dict(literature=paper, sql=sql, mixed=mixed, non_paper=paper)
        output = {key: summarize(rows, folders[key]) for key, rows in output.items()}
    print(json.dumps(output, ensure_ascii=False, indent=2))
