"""Shared metrics, calibration, and summary helpers for agent evaluation reports."""
import copy
import json
import statistics
from pathlib import Path


def apply(review, change):
    parts = change['path'].split('.')
    obj = review
    for key in parts[:-1]:
        if isinstance(obj, list):
            obj = next(x for x in obj if x.get('id') == key or x.get('claim_id') == key or x.get('ref') == key)
        else:
            obj = obj[key]
    obj[parts[-1]] = change['value']


def calibrate(raw, notes):
    v = copy.deepcopy(raw)
    for c in notes['changes']:
        parts = c['path'].split('.')
        if parts[0] == 'citation_assessments':
            p = next(p for p in v['citation_assessments'] if p['claim_id'] == parts[1] and p['ref'] == parts[2])
            p[parts[3]] = c['value']
        else:
            apply(v, c)
    return v


def metrics(case, v, result):
    points = [p for p in v['key_point_scores'].values() if p is not None]
    facts = [c for c in v['claim_assessments'] if c['claim_type'] == 'fact']
    ids = {c['id'] for c in facts}
    pairs = [p for p in v['citation_assessments'] if p['claim_id'] in ids and p['score'] is not None] if case['citation_applicable'] else []
    groups = [p for p in v['citation_group_assessments'] if p['claim_id'] in ids] if case['citation_applicable'] else []
    out = dict(
        point_score=100 * statistics.mean(points) if points else None,
        point_count=len(points),
        fact_count=len(facts),
        supported_facts=sum(c['support'] == 'supported' for c in facts),
        pair_count=len(pairs),
        supported_pairs=sum(p['score'] for p in pairs),
        group_count=len(groups),
        covered_groups=sum(p['coverage'] == 'complete' for p in groups),
        boundary=v['answerability_score'],
    )
    for name, n, d in [
        ('fact_support', 'supported_facts', 'fact_count'),
        ('citation_precision', 'supported_pairs', 'pair_count'),
        ('citation_coverage', 'covered_groups', 'group_count'),
    ]:
        out[name] = 100 * out[n] / out[d] if out[d] else None
    completed = result.get('status') == 'completed' and bool(result.get('answer', '').strip())
    format_ok = True
    if case['id'] == 'FS8-030':
        try:
            format_ok = isinstance(json.loads(result.get('answer', '')), list)
        except ValueError:
            format_ok = False
    out['strict_pass'] = (
        completed
        and bool(points)
        and all(p == 1 for p in points)
        and v['answerability_score'] == 2
        and all(c['support'] == 'supported' for c in v['claim_assessments'])
        and all(p['score'] == 1 for p in pairs)
        and all(p['coverage'] == 'complete' for p in groups)
        and format_ok
    )
    out['format_ok'] = format_ok
    return out


def summary(rows, arm):
    out = {
        'count': len(rows),
        'point_score': statistics.mean(r[arm]['point_score'] for r in rows),
        'strict_pass_count': sum(r[arm]['strict_pass'] for r in rows),
        'boundary_mean': statistics.mean(r[arm]['boundary'] for r in rows),
    }
    for name, n, d in [
        ('fact_support', 'supported_facts', 'fact_count'),
        ('citation_precision', 'supported_pairs', 'pair_count'),
        ('citation_coverage', 'covered_groups', 'group_count'),
    ]:
        den = sum(r[arm][d] for r in rows)
        num = sum(r[arm][n] for r in rows)
        out[name] = dict(percent=100 * num / den if den else None, numerator=num, denominator=den)
    return out
