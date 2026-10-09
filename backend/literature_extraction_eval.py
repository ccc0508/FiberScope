"""Compare reviewed literal extraction references with candidate measurements."""
import csv
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from literature_extraction import normalized, unit_text


def evaluate(task: dict, benchmark: Path):
    metadata = json.loads((benchmark / 'metadata.json').read_text(encoding='utf-8'))
    source = task['source']
    document_mode = source.get('mode') == 'document'
    if (source['pdf_sha256'] != metadata['source_pdf_sha256'] or (not document_mode and (
        source['page'] != metadata['source_pdf_page'] or normalized(source['table']) != normalized(metadata['source_table'])))):
        raise ValueError('Benchmark PDF version, page or table does not match this task.')
    with (benchmark / 'table3_measurements.csv').open(encoding='utf-8-sig', newline='') as f:
        expected = list(csv.DictReader(f))
    actual = (task.get('snapshot') or {}).get('result', {}).get('measurements', [])
    if document_mode:
        actual = [r for r in actual if r.get('source_pdf_page') == metadata['source_pdf_page']
                  and normalized(r.get('source_table','').rstrip('.:：')) == normalized(metadata['source_table'])]

    def key(r, original=False):
        return (normalized(r['raw_material_original'] if original else r['raw_material']), r['metric'], r['measurement_state'])

    reference = {key(r, True): r for r in expected}
    counts = Counter(key(r) for r in actual)
    actual_by_key = {key(r): r for r in actual}
    missing = sorted(set(reference) - set(actual_by_key))
    unexpected = sorted(set(actual_by_key) - set(reference))
    incorrect, correct = [], 0
    for k in sorted(set(reference) & set(actual_by_key)):
        wanted, got = reference[k], actual_by_key[k]
        issues = []
        try:
            if Decimal(wanted['raw_value']) != Decimal(str(got['value'])) or normalized(wanted['raw_value']) != normalized(got['raw_value']):
                issues.append('value')
        except Exception:
            issues.append('value')
        if unit_text(wanted['raw_unit']) != unit_text(got['raw_unit']):
            issues.append('unit')
        bbox = json.loads(wanted['source_bbox_pt'])
        if len(got.get('source_bbox_pt', [])) != 4 or any(abs(a-b) > 0.1 for a,b in zip(bbox, got['source_bbox_pt'])):
            issues.append('source_position')
        if counts[k] > 1:
            issues.append('duplicate')
        if issues:
            incorrect.append({'key': list(k), 'issues': issues})
        else:
            correct += 1
    actual_count = len(actual)
    return {
        'benchmark_id': metadata['benchmark_id'], 'task_id': task['id'], 'task_status': task['status'],
        'model': (task.get('snapshot') or {}).get('configuration', {}).get('llm_model'),
        'scope': 'one_table_literal_extraction; not cross-paper generalization or scientific validation',
        'document_mode': document_mode,
        'reference_measurements': len(expected), 'candidate_measurements': actual_count,
        'correct_measurements': correct, 'missing_count': len(missing), 'unexpected_count': len(unexpected),
        'incorrect_count': len(incorrect), 'duplicate_extra_count': sum(max(0, v-1) for v in counts.values()),
        'precision': correct / actual_count if actual_count else 0,
        'recall': correct / len(expected) if expected else 0,
        'missing': [list(k) for k in missing], 'unexpected': [list(k) for k in unexpected], 'incorrect': incorrect,
    }
