"""Aggregate explicit source-based reviews; never infer semantic grades from keywords."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from validate_qa_eval import digest, read_json, read_jsonl, require
from run_qa_baseline import write_json

SUPPORT = {'supported': 1, 'partially_supported': .5, 'unsupported': 0, 'contradicted': 0}


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def percentile_nearest_rank(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def verify_review(case, result, review, result_path):
    require(review['run_id'] == result['run_id'], 'Review run mismatch')
    require(review['response_file_sha256'] == digest(result_path), 'Reviewed response was changed')
    require(review['review_status'] == 'ai_source_reviewed', 'Review provenance must disclose AI source review')
    points = {p['id']: p for p in case['key_points']}
    scores = review['key_point_scores']
    require(set(scores) == set(points), 'Incomplete key point review')
    require(all(type(v) in (int, float) and v in (0, .5, 1) for v in scores.values()), 'Invalid key point score')
    require(type(review['answerability_score']) is int and review['answerability_score'] in (0, 1, 2), 'Invalid boundary score')
    require(review['observed_behavior'] in {'answer', 'partial', 'abstain', 'flag_conflict'}, 'Invalid observed behavior')
    require(isinstance(review['critical_errors'], list), 'Missing critical error review')
    require(set(review['point_notes']) == set(points) and all(review['point_notes'].values()), 'Missing point justification')
    require(set(review['retrieval_point_assessments']) == set(points), 'Incomplete retrieval review')
    for key, point in points.items():
        value = review['retrieval_point_assessments'][key]
        choices = {'not_applicable'} if point['kind'] in {'scope_limit', 'corpus_scope'} else {'complete', 'partial', 'missing'}
        require(value in choices, 'Invalid retrieval assessment')

    generated = (result.get('response') or {}).get('claims', [])
    claims = review['claim_assessments']
    require([c['id'] for c in claims] == [f'C{i+1}' for i in range(len(generated))], 'Incomplete claim review')
    for original, assessment in zip(generated, claims):
        require(original['text'] == assessment['text'], 'Claim review text mismatch')
        require(assessment['support'] in SUPPORT and type(assessment['citation_required']) is bool, 'Invalid claim support')
        require(bool(assessment['basis']), 'Missing source support rationale')
    expected_pairs = {(f'C{i+1}', ref) for i, c in enumerate(generated) for ref in c['citation_refs']}
    pairs = review['citation_assessments']
    actual_pairs = [(p['claim_id'], p['ref']) for p in pairs]
    require(len(actual_pairs) == len(set(actual_pairs)) and set(actual_pairs) == expected_pairs, 'Incomplete citation pair review')
    by_ref = {e['ref']: e for e in (result.get('response') or {}).get('retrieved_evidence', [])}
    for pair in pairs:
        require(type(pair['score']) is int and pair['score'] in (0, 1), 'Invalid citation score')
        require(bool(pair['basis']), 'Missing citation justification')
        require(pair['ref'] in by_ref, 'Unknown cited reference')
        require(pair['chunk_id'] == by_ref[pair['ref']]['chunk_id'], 'Citation review source mismatch')


def summarize(run_dir, reviews_path):
    run_dir = Path(run_dir).resolve()
    metadata = read_json(run_dir / 'run.json')
    if metadata.get('evaluation_schema_version')==2:
        from score_qa_eval_v2 import summarize as summarize_v2
        return summarize_v2(run_dir,reviews_path)
    cases = read_jsonl(run_dir / 'dataset/cases.jsonl') if (run_dir / 'dataset/cases.jsonl').exists() else None
    require(cases is not None, 'Run dataset missing')
    reviews = read_jsonl(reviews_path)
    by_id = {r['case_id']: r for r in reviews}
    require(len(by_id) == len(reviews) and set(by_id) == {c['id'] for c in cases}, 'Complete one-per-case reviews required')
    rows, all_claims, all_pairs = [], [], []
    tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    usage_known = generation_calls = extra_attempts = 0
    embedding_usage_known = 0
    for case in cases:
        path = run_dir / 'results' / (case['id'] + '.json')
        result, review = read_json(path), by_id[case['id']]
        require(result['case_id'] == case['id'] and result['question'] == case['question'], 'Result input mismatch')
        require(result['status'] in {'answered', 'refused'}, 'Execution failure cannot be semantically graded; report failed runs separately')
        verify_review(case, result, review, path)
        claims, pairs = review['claim_assessments'], review['citation_assessments']
        all_claims.extend(claims)
        all_pairs.extend(pairs)
        required = [c for c in claims if c['citation_required']]
        covered = sum(any(p['claim_id'] == c['id'] and p['score'] == 1 for p in pairs) for c in required)
        point_mean = statistics.mean(review['key_point_scores'].values())
        precision = ratio(sum(p['score'] for p in pairs), len(pairs))
        coverage = ratio(covered, len(required))
        retrieval = [v for v in review['retrieval_point_assessments'].values() if v != 'not_applicable']
        strict = (point_mean == 1 and review['answerability_score'] == 2 and not review['critical_errors']
                  and all(c['support'] == 'supported' for c in claims)
                  and (not required or coverage['value'] == 1)
                  and (not pairs or precision['value'] == 1))
        response = result['response']
        calls = response.get('generation_calls', [])
        generation_calls += len(calls)
        extra_attempts += max(0, len(calls) - 1)
        for call in calls:
            usage = call.get('usage')
            if isinstance(usage, dict) and all(type(usage.get(k)) is int for k in tokens):
                usage_known += 1
                for key in tokens:
                    tokens[key] += usage[key]
        embedding_usage_known += isinstance(response.get('embedding_usage'), dict)
        rows.append({'case_id': case['id'], 'category': case['category'], 'expected_behavior': case['expected_behavior'],
                     'observed_behavior': review['observed_behavior'], 'runtime_status': result['status'],
                     'point_mean': point_mean, 'point_sum': sum(review['key_point_scores'].values()),
                     'point_count': len(review['key_point_scores']), 'answerability_score': review['answerability_score'],
                     'claim_support': ratio(sum(SUPPORT[c['support']] for c in claims), len(claims)),
                     'claim_support_counts': dict(Counter(c['support'] for c in claims)),
                     'citation_precision': precision, 'citation_coverage': coverage,
                     'retrieval_complete': ratio(retrieval.count('complete'), len(retrieval)),
                     'strict_pass': strict, 'end_to_end_ms': result['end_to_end_ms'],
                     'generation_calls': len(calls), 'notes': review['notes']})

    required_total = sum(r['citation_coverage']['denominator'] for r in rows)
    covered_total = sum(r['citation_coverage']['numerator'] for r in rows)
    applicable = [r['retrieval_complete']['value'] for r in rows if r['retrieval_complete']['value'] is not None]
    abstention = [r for r in rows if r['expected_behavior'] == 'abstain']
    answerable = [r for r in rows if r['expected_behavior'] == 'answer']
    source_manifest = read_json(run_dir / 'dataset/manifest.json')
    summary = dict(schema_version=1, run_id=metadata['run_id'], review_provenance='AI source review; independent expert review pending',
                   source_commit=metadata['source_commit'], baseline_id=metadata['baseline_id'],
                   dataset_id=source_manifest['dataset_id'], dataset_manifest_sha256=metadata['dataset_manifest_sha256'],
                   rubric_id=source_manifest['rubric_id'], run_metadata_sha256=digest(run_dir / 'run.json'),
                   reviews_sha256=digest(reviews_path), response_file_hashes={c['id']: digest(run_dir / 'results' / (c['id'] + '.json')) for c in cases},
                   completed=len(rows), total=len(cases), runtime_status_counts=dict(Counter(r['runtime_status'] for r in rows)),
                   expected_behavior_counts=dict(Counter(r['expected_behavior'] for r in rows)),
                   observed_behavior_counts=dict(Counter(r['observed_behavior'] for r in rows)),
                   point_macro_average=statistics.mean(r['point_mean'] for r in rows),
                   point_micro=ratio(sum(r['point_sum'] for r in rows), sum(r['point_count'] for r in rows)),
                   strict_pass=ratio(sum(r['strict_pass'] for r in rows), len(rows)),
                   claim_support=ratio(sum(SUPPORT[c['support']] for c in all_claims), len(all_claims)),
                   claim_support_counts=dict(Counter(c['support'] for c in all_claims)),
                   citation_precision=ratio(sum(p['score'] for p in all_pairs), len(all_pairs)),
                   citation_coverage=ratio(covered_total, required_total),
                   retrieval_complete=ratio(sum(r['retrieval_complete']['numerator'] for r in rows), sum(r['retrieval_complete']['denominator'] for r in rows)),
                   retrieval_macro_average=statistics.mean(applicable) if applicable else None,
                   abstention_boundary_correct=ratio(sum(r['observed_behavior'] == 'abstain' and r['answerability_score'] == 2 for r in abstention), len(abstention)),
                   answerable_wrong_abstention=ratio(sum(r['observed_behavior'] == 'abstain' for r in answerable), len(answerable)),
                   latency_ms={'median': statistics.median(r['end_to_end_ms'] for r in rows),
                               'p95_nearest_rank': percentile_nearest_rank([r['end_to_end_ms'] for r in rows], .95),
                               'total_worker_wall_ms': sum(r['end_to_end_ms'] for r in rows),
                               'scope': 'Runner elapsed time including isolated process startup; excludes HTTP queues and browser rendering.'},
                   generation={'application_calls': generation_calls, 'extra_application_attempts': extra_attempts,
                               'usage_known_calls': usage_known, 'known_usage_tokens': tokens if usage_known else None,
                               'network_retry_count': None},
                   embedding={'query_count': len(rows), 'usage_known_queries': embedding_usage_known, 'tokens': None},
                   rows=rows)
    summary['by_category'] = {category: {'cases': len(group), 'point_macro_average': statistics.mean(r['point_mean'] for r in group),
                                        'strict_pass': ratio(sum(r['strict_pass'] for r in group), len(group))}
                              for category in sorted({r['category'] for r in rows})
                              for group in [[r for r in rows if r['category'] == category]]}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run_dir, args.reviews)
    write_json(args.output, result)
    keys=('run_id','total_tasks','by_suite') if result.get('schema_version')==2 else ('run_id','completed','point_macro_average','strict_pass','citation_precision','claim_support','latency_ms')
    print(json.dumps({key:result[key] for key in keys},ensure_ascii=False))


if __name__ == '__main__':
    main()
