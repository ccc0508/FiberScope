"""Validate a QA evaluation pack offline; this does not run or grade answers."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / 'data/literature/qa-evaluation/pfi-v1'
PACK_FILES = {'cases.jsonl', 'evidence.json', 'rubric.json',
              'scorecard.template.jsonl', 'QUESTIONS.md'}
CATEGORIES = {'factual', 'numeric', 'comparison', 'method', 'mechanism',
              'synthesis', 'source_conflict', 'insufficient_evidence', 'partial_answer'}
BEHAVIORS = {'answer', 'flag_conflict', 'abstain', 'partial'}
POINT_KINDS = {'direct', 'derived', 'bounded_inference', 'scope_limit', 'corpus_scope'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(text):
    return ''.join(unicodedata.normalize('NFKC', text).split()).replace('\u00ad', '')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_jsonl(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        require(bool(line.strip()), f'{Path(path).name}:{line_number}: empty JSONL row')
        row = json.loads(line)
        require(isinstance(row, dict), f'{Path(path).name}:{line_number}: expected object')
        rows.append(row)
    return rows


def child(root, name):
    require(isinstance(name, str) and bool(name) and '\\' not in name, 'Invalid relative path')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts, 'Path escapes source root')
    result = (root / name).resolve()
    require(result.is_relative_to(root.resolve()), 'Path escapes source root')
    return result


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unique_ids(items, label):
    require(isinstance(items, list) and bool(items), f'{label}: empty collection')
    require(all(isinstance(item, dict) and nonempty(item.get('id')) for item in items),
            f'{label}: missing ID')
    ids = [item['id'] for item in items]
    require(len(ids) == len(set(ids)), f'{label}: duplicate ID')
    return set(ids)


def validate_sources(pack_manifest, evidence, baseline):
    """Read frozen metadata using mode=ro; never open the vector index or private config."""
    baseline = Path(baseline).resolve()
    path = child(baseline, 'manifest.json')
    require(digest(path) == pack_manifest['baseline_manifest_sha256'], 'Baseline manifest fingerprint mismatch')
    frozen = read_json(path)
    require(frozen['baseline_id'] == pack_manifest['baseline_id'], 'Baseline ID mismatch')
    require(frozen['source_commit'] == pack_manifest['baseline_source_commit'], 'Baseline source commit mismatch')
    document_by_id = {d['id']: d for d in frozen['documents']}
    expected_documents = {d['id']: d for d in pack_manifest['source_documents']}
    require(set(document_by_id) == set(expected_documents), 'Frozen corpus document set mismatch')
    for document_id, expected in expected_documents.items():
        actual = document_by_id[document_id]
        require(all(actual[k] == expected[k] for k in ('filename', 'file_hash', 'page_count', 'chunk_count')),
                'Frozen document metadata mismatch')
        pdf = child(baseline, 'library/' + actual['snapshot_path'])
        require(digest(pdf) == expected['file_hash'], 'Source PDF fingerprint mismatch')
    metadata = child(baseline, 'library/metadata.sqlite3')
    require(digest(metadata) == frozen['files']['library/metadata.sqlite3'], 'Frozen metadata fingerprint mismatch')
    with closing(sqlite3.connect(metadata.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        require(connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Metadata integrity failed')
        require(connection.execute('SELECT count(*) FROM chunks').fetchone()[0] == frozen['chunk_count'],
                'Frozen chunk count mismatch')
        for item in evidence:
            row = connection.execute('SELECT * FROM chunks WHERE id=?', (item['baseline_chunk_id'],)).fetchone()
            require(row is not None, item['id'] + ': unknown frozen chunk')
            require(row['document_id'] == item['document_id'], item['id'] + ': wrong document')
            require(row['page_start'] <= item['pdf_page'] <= row['page_end'], item['id'] + ': wrong page')
            require(normalized(item['quote']) in normalized(row['text']), item['id'] + ': quote not in frozen chunk')
    return 'pdf_hash_metadata_page_and_quote_passed'


def validate(pack=DEFAULT_PACK, baseline=None):
    pack = Path(pack).resolve()
    manifest = read_json(pack / 'manifest.json')
    require(manifest.get('schema_version') == 1, 'Unsupported pack schema')
    require(manifest.get('review_status') == 'source_checked_ai_draft', 'Review status must disclose provisional source review')
    require(manifest.get('quality_run_status') == 'not_run', 'A dataset pack cannot claim a completed quality run')
    require(set(manifest.get('files', {})) == PACK_FILES, 'Pack file inventory mismatch')
    actual_files = {p.relative_to(pack).as_posix() for p in pack.rglob('*') if p.is_file()}
    require(actual_files == PACK_FILES | {'manifest.json'}, 'Unexpected or missing pack files')
    for name, checksum in manifest['files'].items():
        require(digest(child(pack, name)) == checksum, name + ': checksum mismatch')

    cases, evidence = read_jsonl(pack / 'cases.jsonl'), read_json(pack / 'evidence.json')
    case_ids = unique_ids(cases, 'Cases')
    evidence_ids = unique_ids(evidence, 'Evidence')
    require(len(cases) == manifest['case_count'], 'Case count mismatch')
    require(len(evidence) == manifest['evidence_count'], 'Evidence count mismatch')
    documents = manifest['source_documents']
    unique_ids(documents, 'Documents')
    page_counts = {d['id']: d['page_count'] for d in documents}
    for item in evidence:
        require(item.get('document_id') in page_counts, item['id'] + ': unknown document')
        page = item.get('pdf_page')
        require(type(page) is int and 1 <= page <= page_counts[item['document_id']], item['id'] + ': invalid page')
        require(all(nonempty(item.get(k)) for k in ('baseline_chunk_id', 'locator', 'quote')), item['id'] + ': missing locator or quote')
        require(item.get('verification') == 'pdf_visual_and_frozen_chunk_checked', item['id'] + ': missing source verification label')

    questions = set()
    used_evidence = set()
    point_count = 0
    for case in cases:
        label = case['id']
        require(bool(re.fullmatch(r'PFI-\d{3}', label)), 'Invalid case ID')
        require(case.get('category') in CATEGORIES, label + ': invalid category')
        require(case.get('difficulty') in {'easy', 'medium', 'hard'}, label + ': invalid difficulty')
        require(case.get('expected_behavior') in BEHAVIORS, label + ': invalid behavior')
        require(all(nonempty(case.get(k)) for k in ('question', 'reference_answer')), label + ': missing question or reference')
        question = normalized(case['question'])
        require(question not in questions, label + ': duplicate question')
        questions.add(question)
        expected_category = {'source_conflict': 'flag_conflict', 'partial_answer': 'partial',
                             'insufficient_evidence': 'abstain'}.get(case['category'], 'answer')
        require(case['expected_behavior'] == expected_category, label + ': category/behavior mismatch')
        if case['expected_behavior'] in {'partial', 'abstain'}:
            require(nonempty(case.get('absence_reason')), label + ': missing absence rationale')
        errors = case.get('critical_errors')
        require(isinstance(errors, list) and bool(errors) and all(nonempty(v) for v in errors), label + ': missing critical errors')
        unique_ids(case.get('key_points'), label + ' points')
        for point in case['key_points']:
            point_count += 1
            require(nonempty(point.get('text')) and point.get('kind') in POINT_KINDS, label + ': invalid point')
            refs = point.get('evidence_ids')
            require(isinstance(refs, list) and all(isinstance(ref, str) for ref in refs), label + ': invalid evidence references')
            require(len(refs) == len(set(refs)) and set(refs) <= evidence_ids, label + ': unknown or duplicate evidence')
            require(refs or point['kind'] == 'corpus_scope', label + ': missing supporting context')
            require(point.get('evidence_requirement') in {'all', 'any'}, label + ': invalid evidence requirement')
            used_evidence.update(refs)
            numbers = point.get('numeric_checks')
            require(isinstance(numbers, list), label + ': invalid numeric checks')
            for number in numbers:
                require(isinstance(number, dict) and all(nonempty(number.get(k)) for k in ('label', 'unit')),
                        label + ': missing numeric role or unit')
                for key in ('value', 'absolute_tolerance'):
                    value = number.get(key)
                    require(type(value) in (int, float) and math.isfinite(value), label + ': non-finite numeric value')
                require(number['absolute_tolerance'] >= 0, label + ': negative numeric tolerance')
    require(used_evidence == evidence_ids, 'Unused evidence in pack')
    require(point_count == manifest['key_point_count'], 'Key point count mismatch')
    for field in ('category', 'difficulty', 'expected_behavior'):
        require(dict(Counter(c[field] for c in cases)) == manifest['counts_by_' + field], field + ' count mismatch')

    rubric = read_json(pack / 'rubric.json')
    require(rubric['id'] == manifest['rubric_id'], 'Rubric ID mismatch')
    require(rubric['mode'] == 'source_grounded_manual_review', 'Unexpected automatic grading claim')
    require(set(rubric['key_point_scores']) == {'0', '0.5', '1'}, 'Unsupported point scoring scale')
    require(set(rubric['answerability_scores']) == {'0', '1', '2'}, 'Unsupported behavior scoring scale')
    scorecards = read_jsonl(pack / 'scorecard.template.jsonl')
    require(len(scorecards) == len(cases) and {s['case_id'] for s in scorecards} == case_ids,
            'Scorecard case coverage mismatch')
    points_by_case = {c['id']: {p['id'] for p in c['key_points']} for c in cases}
    for card in scorecards:
        require(card['review_status'] == 'unreviewed', 'Template contains completed review')
        require(set(card['key_point_scores']) == points_by_case[card['case_id']], 'Scorecard point coverage mismatch')
        require(all(v is None for v in card['key_point_scores'].values()), 'Template must not prefill scores')
        require(all(card[k] is None for k in ('run_id', 'reviewer', 'answerability_score', 'claim_assessments',
                                              'citation_assessments', 'retrieval_point_assessments', 'critical_errors')),
                'Template must not contain purported evaluation results')

    source_check = validate_sources(manifest, evidence, baseline) if baseline is not None else 'not_requested'
    return dict(dataset_id=manifest['dataset_id'], cases=len(cases), key_points=point_count, evidence=len(evidence),
                counts_by_expected_behavior=manifest['counts_by_expected_behavior'],
                pack_validation='passed', source_check=source_check, quality_evaluation='not_run', provider_calls=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=DEFAULT_PACK)
    parser.add_argument('--baseline', type=Path, help='Optional frozen baseline; enables PDF hashes and source quote validation')
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.pack, args.baseline), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(1, 'QA evaluation pack validation failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
