"""Baseline evidence preservation, including committed WAL and tamper detection."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

MODULE = Path(__file__).resolve().parents[2] / 'scripts/freeze_qa_baseline.py'
spec = importlib.util.spec_from_file_location('freeze_qa_baseline', MODULE)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_online_backup_includes_committed_wal_without_changing_source(tmp_path):
    source, target = tmp_path / 'source.sqlite3', tmp_path / 'target.sqlite3'
    connection = sqlite3.connect(source)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('CREATE TABLE records(value TEXT)')
        connection.execute("INSERT INTO records VALUES('committed')")
        connection.commit()
        assert Path(str(source) + '-wal').stat().st_size > 0
        before = baseline.database_fingerprint(source)
        baseline.backup_database(source, target)
        assert baseline.database_fingerprint(source) == before
        with baseline.read_database(target) as copied:
            assert copied.execute('SELECT value FROM records').fetchone()[0] == 'committed'
    finally:
        connection.close()


@pytest.fixture
def frozen(tmp_path):
    library = tmp_path / 'library'
    (library / 'papers').mkdir(parents=True)
    pdf = library / 'papers/example.pdf'
    pdf.write_bytes(b'%PDF baseline source fixture')
    connection = sqlite3.connect(library / 'metadata.sqlite3')
    connection.execute('CREATE TABLE chunks(id TEXT)')
    connection.execute("INSERT INTO chunks VALUES('chunk-1')")
    connection.commit()
    connection.close()
    manifest = {'baseline_id': 'fixture', 'chunk_count': 1,
                'documents': [{'snapshot_path': 'papers/example.pdf', 'file_hash': baseline.digest(pdf)}],
                'files': {p.relative_to(tmp_path).as_posix(): baseline.digest(p)
                          for p in tmp_path.rglob('*') if p.is_file()}}
    baseline.write_json(tmp_path / 'manifest.json', manifest)
    return tmp_path


def test_verify_valid_snapshot(frozen):
    result = baseline.verify(frozen)
    assert result['checksums'] == 'passed'
    assert result['documents'] == result['chunks'] == 1


def test_verify_rejects_modified_original_pdf(frozen):
    (frozen / 'library/papers/example.pdf').write_bytes(b'changed source')
    with pytest.raises(ValueError, match='checksum'):
        baseline.verify(frozen)


def test_verify_rejects_unexpected_files(frozen):
    (frozen / 'extra.txt').write_text('unexpected', encoding='utf-8')
    with pytest.raises(ValueError, match='file set'):
        baseline.verify(frozen)


def test_snapshot_refuses_destination_outside_baseline_directory(tmp_path):
    with pytest.raises(ValueError, match='child directory'):
        baseline.snapshot(tmp_path / 'not-a-baseline')


def test_snapshot_refuses_overwrite_before_loading_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(baseline, 'ROOT', tmp_path)
    monkeypatch.setattr(baseline, 'git', lambda *args: '')
    output = tmp_path / '.rag-data/baselines/existing'
    output.mkdir(parents=True)
    with pytest.raises(ValueError, match='already exists'):
        baseline.snapshot(output)


def test_configuration_never_exports_credentials_or_endpoint_urls(tmp_path, monkeypatch):
    for key in list(__import__('os').environ):
        if key.startswith(('RAG_', 'LITERATURE_')):
            monkeypatch.delenv(key)
    settings = tmp_path / '.env.literature'
    settings.write_text('RAG_LLM_MODEL=fixture\nRAG_LLM_API_KEY=fixture-llm-secret\n'
                        'RAG_EMBEDDING_MODEL=fixture-embed\nRAG_EMBEDDING_DIMENSIONS=4\n'
                        'RAG_EMBEDDING_API_KEY=fixture-embedding-secret\n'
                        'RAG_LLM_BASE_URL=https://private-provider.example/v1\n', encoding='utf-8')
    _, config = baseline.configuration(settings)
    encoded = json.dumps(config)
    assert config['llm_model'] == 'fixture'
    assert 'fixture-llm-secret' not in encoded
    assert 'fixture-embedding-secret' not in encoded
    assert 'private-provider.example' not in encoded
    assert len(config['provider_endpoint_fingerprints']['llm_base_url']) == 64


def test_structure_sources_are_copied_with_checksums(tmp_path):
    source=tmp_path/'source';target=tmp_path/'target';source.mkdir();target.mkdir()
    (source/'structure.json').write_text('{"version":"fixture"}',encoding='utf-8')
    (source/'source-pages.json').write_text('[]',encoding='utf-8')
    expected={name:baseline.digest(source/name) for name in ['structure.json','source-pages.json']}
    baseline.copy_structure_files(source,target,expected)
    assert all(baseline.digest(target/name)==checksum for name,checksum in expected.items())
    (source/'source-pages.json').write_text('["changed"]',encoding='utf-8')
    with pytest.raises(ValueError,match='fingerprint'):
        baseline.copy_structure_files(source,target,expected)


def test_snapshot_uses_explicit_experiment_configuration_without_editing_default(tmp_path,monkeypatch):
    monkeypatch.setattr(baseline,'ROOT',tmp_path)
    monkeypatch.setattr(baseline,'git',lambda *args:'')
    default=tmp_path/'backend/.env.literature';default.parent.mkdir()
    default.write_text('LITERATURE_LIBRARY_DIR=live-library\n',encoding='utf-8')
    selected=tmp_path/'private-experiment.env';selected.write_text('experiment',encoding='utf-8')
    called=[]
    def config(path=None):
        called.append(path)
        raise RuntimeError('stop before library access')
    monkeypatch.setattr(baseline,'configuration',config)
    with pytest.raises(RuntimeError,match='before library'):
        baseline.snapshot(tmp_path/'.rag-data/baselines/experiment',selected)
    assert called==[selected]
    assert default.read_text(encoding='utf-8')=='LITERATURE_LIBRARY_DIR=live-library\n'
