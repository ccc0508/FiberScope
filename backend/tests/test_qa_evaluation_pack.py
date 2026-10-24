"""Offline evaluation material checks: source integrity, scopes and unscored templates."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('validate_qa_eval', ROOT / 'scripts/validate_qa_eval.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def rewrite_file(pack, name, value):
    if name.endswith('.jsonl'):
        (pack / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in value), encoding='utf-8')
    else:
        write_json(pack / name, value)
    manifest = evaluation.read_json(pack / 'manifest.json')
    manifest['files'][name] = evaluation.digest(pack / name)
    write_json(pack / 'manifest.json', manifest)


@pytest.fixture
def pack(tmp_path):
    target = tmp_path / 'pack'
    shutil.copytree(evaluation.DEFAULT_PACK, target)
    return target


@pytest.fixture
def source(pack, tmp_path):
    """Make a synthetic source fixture; tests never require ignored PDFs or production data."""
    root = tmp_path / 'baseline'
    (root / 'library/papers').mkdir(parents=True)
    pdf = root / 'library/papers/fixture.pdf'
    pdf.write_bytes(b'%PDF synthetic fixture for fingerprint testing only')
    expected = evaluation.read_json(pack / 'manifest.json')
    document = dict(expected['source_documents'][0])
    document['file_hash'] = evaluation.digest(pdf)
    document['snapshot_path'] = 'papers/fixture.pdf'
    evidence = evaluation.read_json(pack / 'evidence.json')
    chunks = {}
    for item in evidence:
        chunk = chunks.setdefault(item['baseline_chunk_id'], dict(document_id=item['document_id'],
                                  page=item['pdf_page'], quotes=[]))
        chunk['quotes'].append(item['quote'])
    metadata = root / 'library/metadata.sqlite3'
    with sqlite3.connect(metadata) as connection:
        connection.execute('CREATE TABLE chunks(id TEXT, document_id TEXT, page_start INTEGER, page_end INTEGER, text TEXT)')
        connection.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)',
                               [(key, value['document_id'], value['page'], value['page'], '\n'.join(value['quotes']))
                                for key, value in chunks.items()])
    frozen = dict(baseline_id=expected['baseline_id'], source_commit=expected['baseline_source_commit'],
                  documents=[document], chunk_count=len(chunks),
                  files={'library/metadata.sqlite3': evaluation.digest(metadata)})
    write_json(root / 'manifest.json', frozen)
    expected['source_documents'] = [document]
    expected['baseline_manifest_sha256'] = evaluation.digest(root / 'manifest.json')
    write_json(pack / 'manifest.json', expected)
    return root


def test_checked_in_pack_is_complete_but_has_no_quality_results():
    result = evaluation.validate()
    assert result['cases'] == 30
    assert result['key_points'] == 78
    assert result['evidence'] == 23
    assert result['counts_by_expected_behavior'] == {'answer': 24, 'flag_conflict': 1, 'abstain': 4, 'partial': 1}
    assert result['quality_evaluation'] == 'not_run'
    assert result['source_check'] == 'not_requested'
    assert result['provider_calls'] == 0


def test_accepts_source_and_never_changes_it(pack, source):
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert evaluation.validate(pack, source)['source_check'] == 'pdf_hash_metadata_page_and_quote_passed'
    after = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert after == before


def test_rejects_unacknowledged_case_file_change(pack):
    with (pack / 'cases.jsonl').open('a', encoding='utf-8') as stream:
        stream.write('{}\n')
    with pytest.raises(ValueError, match='checksum mismatch'):
        evaluation.validate(pack)


def test_rejects_extra_pack_files(pack):
    (pack / 'results.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Unexpected or missing'):
        evaluation.validate(pack)


def test_rejects_duplicate_questions_even_with_new_ids(pack):
    cases = evaluation.read_jsonl(pack / 'cases.jsonl')
    cases[1]['question'] = cases[0]['question']
    rewrite_file(pack, 'cases.jsonl', cases)
    with pytest.raises(ValueError, match='duplicate question'):
        evaluation.validate(pack)


def test_rejects_unknown_supporting_evidence(pack):
    cases = evaluation.read_jsonl(pack / 'cases.jsonl')
    cases[0]['key_points'][0]['evidence_ids'] = ['missing-evidence']
    rewrite_file(pack, 'cases.jsonl', cases)
    with pytest.raises(ValueError, match='unknown or duplicate evidence'):
        evaluation.validate(pack)


def test_rejects_unsupported_abstention_without_scope_reason(pack):
    cases = evaluation.read_jsonl(pack / 'cases.jsonl')
    del next(c for c in cases if c['expected_behavior'] == 'abstain')['absence_reason']
    rewrite_file(pack, 'cases.jsonl', cases)
    with pytest.raises(ValueError, match='missing absence rationale'):
        evaluation.validate(pack)


def test_rejects_partial_question_mislabeled_as_fully_answerable(pack):
    cases = evaluation.read_jsonl(pack / 'cases.jsonl')
    next(c for c in cases if c['category'] == 'partial_answer')['expected_behavior'] = 'answer'
    rewrite_file(pack, 'cases.jsonl', cases)
    with pytest.raises(ValueError, match='category/behavior mismatch'):
        evaluation.validate(pack)


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True])
def test_rejects_invalid_numeric_tolerances(pack, value):
    cases = evaluation.read_jsonl(pack / 'cases.jsonl')
    cases[1]['key_points'][0]['numeric_checks'][0]['absolute_tolerance'] = value
    rewrite_file(pack, 'cases.jsonl', cases)
    with pytest.raises(ValueError, match='numeric'):
        evaluation.validate(pack)


def test_rejects_prefilled_quality_score_in_template(pack):
    cards = evaluation.read_jsonl(pack / 'scorecard.template.jsonl')
    cards[0]['key_point_scores']['P1'] = 1
    rewrite_file(pack, 'scorecard.template.jsonl', cards)
    with pytest.raises(ValueError, match='must not prefill scores'):
        evaluation.validate(pack)


def test_rejects_replaced_source_pdf(pack, source):
    next((source / 'library/papers').glob('*.pdf')).write_bytes(b'replaced')
    with pytest.raises(ValueError, match='Source PDF fingerprint mismatch'):
        evaluation.validate(pack, source)


def test_rejects_quote_attributed_to_wrong_source_page(pack, source):
    evidence = evaluation.read_json(pack / 'evidence.json')
    evidence[0]['pdf_page'] += 1
    rewrite_file(pack, 'evidence.json', evidence)
    with pytest.raises(ValueError, match='wrong page'):
        evaluation.validate(pack, source)


def test_rejects_plausible_but_fabricated_source_quote(pack, source):
    evidence = evaluation.read_json(pack / 'evidence.json')
    evidence[0]['quote'] = 'This paper achieved a perfect independent validation score.'
    rewrite_file(pack, 'evidence.json', evidence)
    with pytest.raises(ValueError, match='quote not in frozen chunk'):
        evaluation.validate(pack, source)


def test_rejects_source_manifest_path_escape(pack, source):
    frozen = evaluation.read_json(source / 'manifest.json')
    frozen['documents'][0]['snapshot_path'] = '../../outside.pdf'
    write_json(source / 'manifest.json', frozen)
    manifest = evaluation.read_json(pack / 'manifest.json')
    manifest['baseline_manifest_sha256'] = evaluation.digest(source / 'manifest.json')
    write_json(pack / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='escapes source root'):
        evaluation.validate(pack, source)


def test_reference_percentage_calculations_are_consistent():
    cases = {c['id']: c for c in evaluation.read_jsonl(evaluation.DEFAULT_PACK / 'cases.jsonl')}
    for case_id, before, after in [('PFI-010', 73.23, 69.82), ('PFI-022', 28.23, 23.56)]:
        points = cases[case_id]['key_points']
        difference = points[1]['numeric_checks'][0]
        relative = points[2]['numeric_checks'][0]
        assert difference['value'] == pytest.approx(before - after, abs=difference['absolute_tolerance'])
        assert difference['unit'] == 'percentage_points'
        assert relative['value'] == pytest.approx((before - after) / before * 100, abs=relative['absolute_tolerance'])
        assert relative['unit'] == '%'


def test_conflict_case_preserves_two_separately_located_values():
    case = next(c for c in evaluation.read_jsonl(evaluation.DEFAULT_PACK / 'cases.jsonl') if c['id'] == 'PFI-024')
    assert case['expected_behavior'] == 'flag_conflict'
    abstract, body = case['key_points'][:2]
    assert abstract['numeric_checks'][0]['value'] == .888
    assert body['numeric_checks'][0]['value'] == .912
    assert abstract['evidence_ids'] != body['evidence_ids']
