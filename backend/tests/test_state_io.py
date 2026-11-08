import json
from pathlib import Path

import pytest
from literature_rag import state_io


def test_transient_replace_failure_keeps_old_state_until_retry(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    path.write_text('{"status":"running"}', encoding='utf8')
    original = Path.replace
    calls = []
    def replace(source, target):
        calls.append(1)
        if len(calls) < 3:
            assert json.loads(path.read_text())['status'] == 'running'
            raise PermissionError('file is temporarily busy')
        return original(source, target)
    monkeypatch.setattr(Path, 'replace', replace)
    delays = []
    monkeypatch.setattr(state_io.time, 'sleep', delays.append)
    state_io.save_state(path, {'status': 'completed'})
    assert json.loads(path.read_text())['status'] == 'completed'
    assert delays == [0.05, 0.1]
    assert 'PermissionError' in (tmp_path / 'state-errors.log').read_text()


def test_persistent_permission_failure_is_bounded(tmp_path, monkeypatch):
    def fail(*args):
        raise PermissionError('locked')
    monkeypatch.setattr(Path, 'replace', fail)
    delays = []
    monkeypatch.setattr(state_io.time, 'sleep', delays.append)
    with pytest.raises(PermissionError):
        state_io.save_state(tmp_path / 'state.json', {'status': 'failed'})
    assert len(delays) == 5
    assert (tmp_path / 'state.tmp').exists()


def test_nontransient_io_error_does_not_retry(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(Path, 'replace', fail)
    delays = []
    monkeypatch.setattr(state_io.time, 'sleep', delays.append)
    with pytest.raises(OSError):
        state_io.save_state(tmp_path / 'state.json', {})
    assert delays == []
