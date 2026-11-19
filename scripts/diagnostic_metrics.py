"""Offline evaluation against frozen inputs. Use --help for supported modes."""

import argparse
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from evaluation_groups import ROOT, groups, load

GOLD = ROOT / "data/agent-evaluation/diagnostics-v1"


def digest(value):
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def rate(n, d):
    return {
        "numerator": n,
        "denominator": d,
        "percent": round(100 * n / d, 2) if d else None,
    }


def retrieval(state, relevant):
    pools = {"vector": set(), "vector_at_seed_limit": set(), "reranked": set()}
    calls = []
    for t in state.get("tool_trace", []):
        if (
            t["status"] != "completed"
            or t.get("input", {}).get("tool") != "search_literature"
        ):
            continue
        stages = [
            s for s in t.get("internal_steps", []) if s.get("status") == "completed"
        ]
        vectors = [s for s in stages if s["name"] == "retrieval.vector_search"]
        seeds = [s for s in stages if s["name"] == "retrieval.select_seeds"]
        if (
            not vectors
            or len(seeds) != 1
            or not any(s["name"] == "retrieval.rerank" for s in stages)
        ):
            return {"status": "missing_paired_stages"}
        candidates = {v["chunk_id"] for s in vectors for v in s["output"]["candidates"]}
        k = seeds[0]["input"]["top_k"]
        before_at_k = {
            v["chunk_id"] for s in vectors for v in s["output"]["candidates"][:k]
        }
        selected = set(seeds[0]["output"]["selected_ids"])
        calls.append(
            {
                "id": t["call_id"],
                "vector": sorted(candidates),
                "reranked": sorted(selected),
            }
        )
        calls[-1]["seed_limit"] = k
        calls[-1]["candidate_limits"] = [s["input"]["limit"] for s in vectors]
        calls[-1]["metrics"] = {
            name: {
                "precision": rate(len(ids & relevant), len(ids)),
                "recall": rate(len(ids & relevant), len(relevant)),
            }
            for name, ids in [
                ("vector", candidates),
                ("vector_at_seed_limit", before_at_k),
                ("reranked", selected),
            ]
        }
        pools["vector_at_seed_limit"].update(before_at_k)
        pools["vector"].update(candidates)
        pools["reranked"].update(selected)
    if "tool_calls" in state:
        expected = {
            event["result"]["call_id"]
            for event in state["tool_calls"]
            if event["request"]["tool"] == "search_literature"
            and event["status"] == "completed"
        }
        if expected != {call["id"] for call in calls}:
            return {"status": "missing_paired_stages"}
    if not calls:
        return {
            "status": "no_successful_search"
            if "tool_trace" in state
            else "missing_trace"
        }
    result = {"status": "scored", "searches": calls}
    for stage, found in pools.items():
        hits = relevant & found
        result[stage] = {
            "precision": rate(len(hits), len(found)),
            "recall": rate(len(hits), len(relevant)),
            "relevant_hits": sorted(hits),
            "missed": sorted(relevant - found),
        }
    return result


def same_cell(left, right, tolerance):
    # PostgreSQL NUMERIC values in archived reference rows are decimal strings.
    # Integer-looking text identifiers (for example "001") retain their spelling.
    if isinstance(right, str) and not re.fullmatch(r"-?(?:0|[1-9]\d*)\.\d+", right):
        return left == right
    if (
        left is None
        or right is None
        or isinstance(left, bool)
        or isinstance(right, bool)
    ):
        return type(left) is type(right) and left == right
    try:
        a, b = Decimal(str(left)), Decimal(str(right))
    except InvalidOperation:
        return left == right
    # IDs/counts represented by integer values compare exactly.
    return (
        a.is_finite()
        and b.is_finite()
        and abs(a - b) <= (0 if isinstance(right, int) else tolerance)
    )


def same_rows(got, expected, ordered, tolerance):
    def matches(row, ref):
        return len(row) == len(ref) and all(
            same_cell(a, b, tolerance) for a, b in zip(row, ref)
        )

    if len(got) != len(expected):
        return False
    if ordered:
        return all(matches(a, b) for a, b in zip(got, expected))
    # One-to-one matching preserves duplicates, including near-equal numeric values.
    owners = {}

    def assign(i, seen):
        for j, row in enumerate(expected):
            if j in seen or not matches(got[i], row):
                continue
            seen.add(j)
            if j not in owners or assign(owners[j], seen):
                owners[j] = i
                return True
        return False

    return all(assign(i, set()) for i in range(len(got)))


def projected(results, parts):
    rows = None
    link = None
    for part in parts:
        data = results.get(part["sql"].strip())
        if data is None or data.get("truncated"):
            return None
        cols = data["columns"]
        if any(cols.count(c) != 1 for c in part["columns"]):
            return None
        if len(parts) > 1:
            if len(data["rows"]) != 1 or cols.count(part["join_key"]) != 1:
                return None
            key = data["rows"][0][cols.index(part["join_key"])]
            if key is None or (link is not None and link != key):
                return None
            link = key
        selected = [
            [row[cols.index(c)] for c in part["columns"]] for row in data["rows"]
        ]
        if rows is None:
            rows = selected
        elif len(rows) == len(selected) == 1:
            rows = [rows[0] + selected[0]]
        else:
            return None
    return rows


def sql_case(case, state, refs, rules, adjudication=None):
    events = [
        t
        for t in state["tool_calls"]
        if t["request"]["tool"] == "query_experiment_data"
    ]
    successes = [t for t in events if t["status"] == "completed"]
    result = {"execution": rate(len(successes), len(events))}
    if not case["reference_sql"]:
        return dict(result, status="not_a_result_task")
    if [x["sql"] for x in refs] != case["reference_sql"]:
        raise ValueError("Frozen reference SQL differs from case " + case["id"])
    actual = {t["request"]["sql"].strip(): t["result"]["result"] for t in successes}
    checks = []
    for idx, ref in enumerate(refs):
        exact = actual.get(ref["sql"].strip())
        rows = exact["rows"] if exact and not exact.get("truncated") else None
        if rows is None and rules:
            rows = projected(actual, rules[idx])
        checks.append(
            None
            if rows is None
            else same_rows(
                rows,
                ref["rows"],
                case["id"] in ("SQL02", "SQL03"),
                Decimal("0.0001" if case["id"] == "SQL13" else "0.01"),
            )
        )
    if not successes:
        checks = [False] * len(refs)
    correct = False if False in checks else None if None in checks else True
    if correct is None and adjudication:
        if (
            adjudication["fingerprint"] != digest([events, refs])
            or type(adjudication["correct"]) is not bool
            or not adjudication["reason"].strip()
        ):
            raise ValueError("Stale or incomplete SQL adjudication for " + case["id"])
        correct = adjudication["correct"]
    return dict(
        result,
        checks=checks,
        correct=correct,
        status="review_required" if correct is None else "scored",
    )


def mixed_packet(case, state, needs):
    calls = []
    for child in state["children"]:
        for event in child["trace"]["tool_calls"]:
            calls.append(
                {
                    "role": child["role"],
                    "request": event["request"],
                    "status": event["status"],
                    "error": event.get("result", {}).get("error_code"),
                    "call_id": event.get("result", {}).get("call_id"),
                }
            )
    evidence = {}
    specialist_findings = []
    for m in reversed(state.get("model_calls", [])):
        if m["stage"] != "synthesis_review":
            continue
        found_payload = False
        for msg in m["input_messages"]:
            if msg["role"] != "user":
                continue
            content = msg["content"]
            texts = (
                [content]
                if isinstance(content, str)
                else [v["text"] for v in content if v.get("type") == "text"]
            )
            for text in texts:
                try:
                    payload = json.loads(text)
                except ValueError:
                    continue
                if isinstance(payload, dict) and "evidence" in payload:
                    found_payload = True
                    specialist_findings = payload.get("specialists", [])
                    for i, source in enumerate(payload["evidence"], 1):
                        evidence[f"e{i}"] = source
        if not found_payload:
            raise ValueError(
                "Cannot reconstruct the final synthesis input for " + state["run_id"]
            )
        break
    return {
        "case": case,
        "run_id": state["run_id"],
        "calls": calls,
        "needs": needs,
        "evidence": evidence,
        "specialist_findings": specialist_findings,
    }


def mixed_case(packet, review):
    if not review:
        return {"status": "review_required"}
    if review["fingerprint"] != digest(packet):
        raise ValueError("Review and original trace differ: " + packet["run_id"])
    if len(review["calls"]) != len(packet["calls"]) or len(review["needs"]) != len(
        packet["needs"]
    ):
        raise ValueError(
            "Review must cover every proposal and every evidence requirement"
        )
    for verdict in review["calls"]:
        if type(verdict["correct"]) is not bool or not verdict["reason"].strip():
            raise ValueError("Missing tool judgment")
    for item in review["needs"]:
        if (
            not isinstance(item["sources"], list)
            or not set(item["sources"]) <= packet["evidence"].keys()
            or not item["reason"].strip()
        ):
            raise ValueError(
                "Evidence judgment must refer to the supplied synthesis context"
            )
        if any(
            packet["evidence"][key].get("status") != "completed"
            for key in item["sources"]
        ):
            raise ValueError(
                "A failed or blocked tool call cannot supply required evidence"
            )
    return {
        "status": "scored",
        "tools": rate(sum(v["correct"] for v in review["calls"]), len(packet["calls"])),
        "evidence": rate(
            sum(bool(v["sources"]) for v in review["needs"]), len(packet["needs"])
        ),
    }


def pooled(values):
    return rate(
        sum(v["numerator"] for v in values), sum(v["denominator"] for v in values)
    )


def evaluate(suite, run, reviews, packets):
    cases = groups()[suite]
    rows = {}
    if suite == "literature":
        gold = load(GOLD / "chunk-qrels.json")
        manifest = load(run / "manifest.json")
        while isinstance(manifest.get("baseline"), dict):
            manifest = manifest["baseline"]
        if (
            manifest.get("metadata_hash", manifest.get("library"))
            != gold["metadata_sha256"]
        ):
            raise ValueError("Retrieval qrels require the same frozen chunk index")
    if suite == "sql":
        refs = load(run / "sql-references.json")
        rules = load(GOLD / "sql-projections.json")
        cases = load(ROOT / "data/text-to-sql-evaluation/cases-v1.json")
    if suite == "mixed":
        needs = load(GOLD / "mixed-needs.json")
    for case in cases:
        k = case["id"]
        path = run / (k + ".json")
        if not path.exists():
            rows[k] = {"status": "missing_case"}
            continue
        state = load(path)
        if state["case_id"] != k or state["question"] != case["question"]:
            raise ValueError("Case identity differs: " + k)
        required_trace = {
            "literature": ("tool_trace",),
            "sql": ("tool_calls",),
            "mixed": ("children", "model_calls"),
        }[suite]
        if any(not isinstance(state.get(field), list) for field in required_trace):
            rows[k] = {"status": "missing_trace"}
            continue
        if suite == "literature":
            row = retrieval(state, set(gold["relevant"][k]))
        elif suite == "sql":
            row = sql_case(case, state, refs[k], rules.get(k), reviews.get(k))
            if packets and row["status"] == "review_required":
                events = [
                    t
                    for t in state["tool_calls"]
                    if t["request"]["tool"] == "query_experiment_data"
                ]
                save(
                    packets / (k + ".json"),
                    {
                        "case": case,
                        "queries": events,
                        "reference": refs[k],
                        "fingerprint": digest([events, refs[k]]),
                    },
                )
        else:
            packet = mixed_packet(case, state, needs[k])
            row = mixed_case(packet, reviews.get(k))
            if packets:
                save(
                    packets / (k + ".json"),
                    {"packet": packet, "fingerprint": digest(packet)},
                )
        rows[k] = row
    summary = {"status_counts": dict(Counter(row["status"] for row in rows.values()))}
    scored = [v for v in rows.values() if v["status"] == "scored"]
    if suite == "literature":
        for stage in ("vector", "vector_at_seed_limit", "reranked"):
            summary[stage] = {
                key: pooled([v[stage][key] for v in scored])
                for key in ("precision", "recall")
            }
    elif suite == "sql":
        summary["execution"] = pooled(
            [v["execution"] for v in rows.values() if "execution" in v]
        )
        summary["result_correct_reviewed"] = rate(
            sum(v["correct"] for v in scored), len(scored)
        )
        summary["result_correct_all"] = (
            summary["result_correct_reviewed"]
            if len(scored) == sum(bool(v["reference_sql"]) for v in cases)
            else None
        )
    else:
        for key in ("tools", "evidence"):
            summary[key] = pooled([v[key] for v in scored])
    return {
        "metric_version": 1,
        "suite": suite,
        "run": run.name,
        "summary": summary,
        "cases": rows,
    }


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["literature", "sql", "mixed"])
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument(
        "--review", type=Path, help="Semantic judgments for this run only"
    )
    parser.add_argument(
        "--packets",
        type=Path,
        help="Write evidence for the reviewer, never passed to the answerer",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        args.suite, args.run, load(args.review) if args.review else {}, args.packets
    )
    save(args.out, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
