"""Offline delivery audit for native preservation, numeric rows, provenance and isolated indexing."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from mineru_quality import table_values
from review_mineru_quality import materialize, load, digest, save, ROOT


def audit(run_dir, report_dir, index_dir):
    run_dir, report_dir, index_dir = map(Path, (run_dir, report_dir, index_dir))
    study, source, jobs, records, units, ledger, organized, info = materialize(run_dir)
    assert info['unflagged_sample_count'] == 0
    assert info['correction_statuses'].get('pending', 0) == 0
    assert digest(ROOT/'backend/.env.literature') == study['answer_model_config_sha256']
    assert load(report_dir/'summary.json') == info
    assert load(report_dir/'corrected-units.json') == units
    original = {u['source_id']: u for u in source['units']}
    updated = {u['source_id']: u for u in units}
    assert original.keys() == updated.keys()
    by_source = {e['source_id']: e for e in ledger}
    data_cells = 0
    for sid, unit in updated.items():
        before = original[sid]
        entry = by_source.get(sid)
        if not entry:
            assert all(unit[k] == v for k,v in before.items())
        else:
            assert before['text'] == entry['original_text'] and unit['text'] == entry['corrected_text']
            reconstructed = before['text']
            for edit in reversed(entry['edits']):
                assert before['text'][edit['original_start']:edit['original_end']] == edit['before']
                reconstructed = reconstructed[:edit['original_start']] + edit['after'] + reconstructed[edit['original_end']:]
            assert reconstructed == unit['text']
        if unit['kind'] == 'table':
            assert table_values(before['text']) == table_values(unit['text'])
            data_cells += sum(len(row) for row in table_values(unit['text']))
    assert all({f['source_id'] for f in j['findings']} == {j['source_id']} for j in jobs)
    # Do not mislabel corrected offsets as literal original-PDF character offsets.
    for chunk in organized['chunks']:
        for span, provenance in zip(chunk['source_spans'], chunk['quality_provenance'], strict=True):
            assert updated[span['source_id']]['text'][span['start']:span['end']] == span['text']
            entry = by_source.get(span['source_id'])
            if entry and entry['status'] == 'accepted_correction':
                assert provenance['offset_space'] == 'corrected_unit'
            for region in provenance['verified_regions']:
                assert chunk['page_start'] <= region['page'] <= chunk['page_end']
    manifest = load(index_dir/'structure.json')
    assert manifest['status'] == 'ready' and manifest['chunks'] == len(organized['chunks'])
    assert digest(index_dir/'quality-ledger.json') == manifest['quality_ledger_sha256']
    assert digest(index_dir/'native-source.json') == manifest['native_source_sha256']
    assert digest(index_dir/'metadata.sqlite3') == manifest['metadata_sha256']
    with sqlite3.connect((index_dir/'metadata.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as conn:
        count = conn.execute('SELECT count(*) FROM chunks').fetchone()[0]
    assert count == len(organized['chunks'])
    previous = load(Path(study['source_dir'])/'structure.json')
    assert digest(Path(study['source_dir'])/'metadata.sqlite3') == previous['metadata_sha256']
    publication = load(report_dir/'publication.json')
    for name, checksum in publication['files'].items():
        assert digest(report_dir/name) == checksum
    calls = [*load(run_dir/'prior-records.json'), *records.values()] if (run_dir/'prior-records.json').exists() else list(records.values())
    signatures = {(r['request_sha256'],r['started_at']) for r in calls}
    assert len(signatures) == info['provider_calls']
    usage = Counter()
    for record in calls:
        usage.update(record.get('usage') or {})
    assert dict(usage) == info['usage']
    result = dict(status='passed', original_units_unchanged_or_reversibly_overlaid=True,
        flagged_units=len(jobs), normal_samples=0, numeric_table_cells_unchanged=data_cells,
        corrected_offsets_and_cross_page_locators=True, old_source_metadata_unchanged=True,
        application_configuration_unchanged=True, isolated_index_chunks=count,
        all_review_calls_counted=len(calls), review_usage=dict(usage),
        returned_models=sorted({r['model_info'].get('returned_model','unknown') for r in calls}),
        embedding_calls=manifest['embedding_calls'], public_file_hashes_verified=True,
        audit_script_sha256=digest(Path(__file__)))
    save(report_dir/'audit.json', result)
    publication['files']['audit.json'] = digest(report_dir/'audit.json')
    publication['method_document_sha256'] = digest(ROOT/'docs/QA_MINERU_QUALITY_20261030.md')
    save(report_dir/'publication.json', publication)
    return result


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--index-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.run_dir,args.report_dir,args.index_dir),ensure_ascii=False))
