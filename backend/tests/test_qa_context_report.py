"""Historical grade reuse must not create new calls or silently change inputs."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import report_qa_context_v1_20261029 as report


def fixture(tmp_path, monkeypatch):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    for root in [old, new]:
        (root / 'inputs').mkdir(parents=True)
        (root / 'records').mkdir()
    jobs = []
    for kind in ['luna', 'jev']:
        for index in range(1, 33):
            name = f'{kind}-synthetic-{index}'
            entry = dict(name=name, judge=kind, task_id=f'PFI2-{index:03}', system='dsh', request_sha256=f'seal-{index}')
            jobs.append(entry)
            content = json.dumps(dict(question=index, model=kind)).encode()
            (old / 'inputs' / (name + '.json')).write_bytes(content)
            (new / 'inputs' / (name + '.json')).write_bytes(content)
            folder = old / 'records' / name
            folder.mkdir()
            (folder / '1.json').write_text(json.dumps(dict(status='completed', api_calls=1, attempt=1)), encoding='utf-8')
    contract = dict(jobs=jobs, policy_sha256='SYNTHETIC_POLICY', requested_judges={'luna': 'L', 'jev': 'J'})
    report.save(old / 'study.json', contract)
    report.save(new / 'study.json', contract)
    monkeypatch.setattr(report, 'OLD_STUDY', old)
    monkeypatch.setattr(report, 'NEW_STUDY', new)
    audited = []
    def audit(*args):
        audited.append(args)
        return (None, None, deepcopy(contract))
    monkeypatch.setattr(report.reporting, 'audit', audit)
    return old, new, jobs, audited


def test_reuse_retains_original_bytes_and_records_zero_new_calls(tmp_path, monkeypatch):
    old, new, jobs, audited = fixture(tmp_path, monkeypatch)
    report.reuse()
    manifest = report.judge.read_json(new / 'reused-dsh-records.json')
    assert audited and manifest['new_provider_calls'] == 0
    assert manifest['identical_inputs_verified'] is True
    assert len(manifest['records']) == 64
    for entry in jobs:
        relative = Path('records') / entry['name'] / '1.json'
        assert (old / relative).read_bytes() == (new / relative).read_bytes()


def test_one_changed_input_prevents_all_reuse_before_any_copy(tmp_path, monkeypatch):
    _, new, jobs, _ = fixture(tmp_path, monkeypatch)
    last = new / 'inputs' / (jobs[-1]['name'] + '.json')
    last.write_bytes(last.read_bytes() + b' ')
    with pytest.raises(ValueError, match='byte-identical'):
        report.reuse()
    assert list((new / 'records').iterdir()) == []
    assert not (new / 'reused-dsh-records.json').exists()


def test_changed_judge_configuration_prevents_reuse(tmp_path, monkeypatch):
    _, new, _, _ = fixture(tmp_path, monkeypatch)
    contract = report.judge.read_json(new / 'study.json')
    contract['requested_judges']['luna'] = 'OTHER_MODEL'
    report.save(new / 'study.json', contract)
    with pytest.raises(ValueError, match='configuration changed'):
        report.reuse()
    assert list((new / 'records').iterdir()) == []


def test_refresh_does_not_overwrite_a_document_changed_since_export(tmp_path, monkeypatch):
    output = tmp_path / 'report'
    output.mkdir()
    document = tmp_path / 'report.md'
    document.write_text('Original report', encoding='utf-8')
    report.save(output / 'publication.json', dict(files={}, document_sha256=report.judge.digest(document)))
    document.write_text('User edited this report', encoding='utf-8')
    monkeypatch.setattr(report, 'OUTPUT', output)
    monkeypatch.setattr(report, 'DOC', document)
    with pytest.raises(ValueError, match='document changed'):
        report.report(refresh=True)
    assert document.read_text(encoding='utf-8') == 'User edited this report'
