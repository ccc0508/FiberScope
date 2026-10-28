"""Freeze and verify a local literature-QA baseline without provider calls."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
PRODUCT_PATHS = ['backend/app', 'backend/literature_rag', 'backend/literature_worker.py',
                 'backend/requirements*.txt', 'frontend/src', 'frontend/vite.config.ts',
                 'frontend/package.json', 'frontend/package-lock.json']


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout.decode('utf-8').strip()


@contextmanager
def read_database(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def backup_database(source, destination):
    # The online API includes committed WAL transactions; copying the main file does not.
    with read_database(source) as original:
        with closing(sqlite3.connect(destination)) as target:
            original.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite backup integrity check failed')


def database_fingerprint(path):
    with read_database(path) as connection:
        connection.execute('BEGIN')
        value = hashlib.sha256()
        for line in connection.iterdump():
            value.update(line.encode('utf-8'))
            value.update(b'\n')
        return value.hexdigest()


def library_fingerprint(root):
    return {'metadata': database_fingerprint(root / 'metadata.sqlite3'),
            'vectors': database_fingerprint(root / 'chroma/chroma.sqlite3'),
            'index_files': {p.relative_to(root).as_posix(): digest(p)
                            for p in sorted((root / 'chroma').rglob('*'))
                            if p.is_file() and not p.name.startswith('chroma.sqlite3')}}


def configuration(env_file=None):
    from app.literature import LiteratureSettings
    from literature_rag.config import Settings
    from literature_rag.diagnostics import configuration_snapshot
    path = env_file or ROOT / 'backend/.env.literature'
    settings = Settings(_env_file=path)
    web = LiteratureSettings(_env_file=path)
    result = configuration_snapshot(path)
    result.update({'chunk_size_setting': settings.chunk_size,
                   'chunk_overlap_setting': settings.chunk_overlap,
                   'chunk_settings_note': 'Settings only; frozen existing chunk contents are authoritative.',
                   'qa_timeout_seconds': web.timeout_seconds,
                   'vector_candidate_limit': 50,
                   'generation_attempt_limit': 2,
                   'generation_parameters': 'Temperature, top_p and seed are not explicitly set by the frozen generator; provider defaults apply.',
                   'provider_endpoint_fingerprints': {
                       key: hashlib.sha256((getattr(settings, key) or '<sdk-default>').encode()).hexdigest()
                       for key in ['llm_base_url', 'embedding_base_url']}})
    if settings.llm_thinking_enabled is not None or settings.llm_reasoning_effort is not None:
        result['generation_parameters'] = (
            f'Thinking enabled={settings.llm_thinking_enabled}; reasoning_effort={settings.llm_reasoning_effort}; '
            'temperature, top_p and seed are not explicitly set; provider defaults apply.')
    return web.root, result


def check_index(root):
    """Runs only on a disposable copy, so Chroma cannot mutate the frozen baseline."""
    os.environ['ANONYMIZED_TELEMETRY'] = 'False'
    import chromadb
    config = json.loads((root / 'configuration.json').read_text(encoding='utf-8'))
    library = root / 'library'
    fingerprint = hashlib.sha256(
        f"{config['embedding_provider']}|{config['embedding_model']}|{config['embedding_dimensions']}".encode()).hexdigest()
    client = chromadb.PersistentClient(str(library / 'chroma'))
    collection = client.get_collection('chunks_' + fingerprint[:12])
    if (collection.metadata or {}).get('fingerprint') != fingerprint:
        raise ValueError('Embedding fingerprint mismatch')
    if (collection.configuration or {}).get('hnsw', {}).get('space') != 'cosine':
        raise ValueError('Unexpected vector distance')
    with read_database(library / 'metadata.sqlite3') as connection:
        expected = {r['id'] for r in connection.execute('SELECT id FROM chunks')}
    records = collection.get(include=['embeddings'])
    if not expected or set(records['ids']) != expected:
        raise ValueError('Vector IDs do not match the frozen chunks')
    if any(len(v) != config['embedding_dimensions'] for v in records['embeddings']):
        raise ValueError('Vector dimension mismatch')
    probe = collection.query(query_embeddings=[records['embeddings'][0].tolist()],
                             n_results=1, include=['distances'])
    if not probe['ids'][0] or probe['ids'][0][0] not in expected:
        raise ValueError('Offline nearest-neighbor probe failed')
    return {'vectors': len(expected), 'dimensions': config['embedding_dimensions'],
            'offline_query': 'passed', 'provider_calls': 0}


def verify_index_on_copy(root):
    temporary_root = ROOT / 'tmp'
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='qa-index-check-', dir=temporary_root) as folder:
        working = Path(folder)
        shutil.copytree(root / 'library', working / 'library')
        shutil.copy2(root / 'configuration.json', working / 'configuration.json')
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(Path(__file__).resolve()),
                                 '_check-index', str(working)],
                                capture_output=True, text=True, encoding='utf-8', timeout=90)
        if result.returncode:
            raise ValueError('Offline index verification failed; baseline not finalized')
        return json.loads(result.stdout)


def verify(root, with_index=False):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    expected_files = manifest['files']
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
                    and p != root / 'manifest.json'}
    if actual_files != set(expected_files):
        raise ValueError('Baseline file set changed')
    for name, expected in expected_files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or digest(path) != expected:
            raise ValueError('Baseline checksum mismatch: ' + name)
    with read_database(root / 'library/metadata.sqlite3') as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Metadata integrity check failed')
        chunks = connection.execute('SELECT count(*) FROM chunks').fetchone()[0]
        for document in manifest['documents']:
            if digest(root / 'library' / document['snapshot_path']) != document['file_hash']:
                raise ValueError('PDF does not match its document fingerprint')
    if chunks != manifest['chunk_count']:
        raise ValueError('Chunk count mismatch')
    result = {'baseline_id': manifest['baseline_id'], 'files': len(expected_files),
              'documents': len(manifest['documents']), 'chunks': chunks, 'checksums': 'passed'}
    if with_index:
        result['index'] = verify_index_on_copy(root)
    return result


def snapshot(output):
    output = Path(output).resolve()
    allowed = (ROOT / '.rag-data/baselines').resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('Snapshot must be a new child directory under .rag-data/baselines')
    if git('diff', '--name-only', 'HEAD', '--', *PRODUCT_PATHS) or git(
            'ls-files', '--others', '--exclude-standard', '--', *PRODUCT_PATHS):
        raise ValueError('Commit or resolve product source changes before freezing')
    if output.exists():
        raise ValueError('Destination already exists; refusing to overwrite the baseline')
    library, config = configuration()
    commit = git('rev-parse', 'HEAD')
    with FileLock(str(library / '.import.lock'), timeout=10):
        before = library_fingerprint(library)
        with read_database(library / 'metadata.sqlite3') as connection:
            documents = [dict(r) for r in connection.execute('SELECT * FROM documents ORDER BY id')]
            chunks = connection.execute('SELECT count(*) FROM chunks').fetchone()[0]
            if not documents or any(d['status'] != 'completed' for d in documents):
                raise ValueError('Library must contain only completed documents')
            if sum(d['chunk_count'] for d in documents) != chunks:
                raise ValueError('Document and chunk counts disagree')
        output.mkdir(parents=True)
        frozen = output / 'library'
        (frozen / 'papers').mkdir(parents=True)
        (frozen / 'chroma').mkdir()
        backup_database(library / 'metadata.sqlite3', frozen / 'metadata.sqlite3')
        backup_database(library / 'chroma/chroma.sqlite3', frozen / 'chroma/chroma.sqlite3')
        for source in sorted((library / 'chroma').rglob('*')):
            if source.is_file() and not source.name.startswith('chroma.sqlite3'):
                if source.is_symlink() or not source.resolve().is_relative_to(library.resolve()):
                    raise ValueError('Index file escapes the library')
                destination = frozen / source.relative_to(library)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if digest(destination) != before['index_files'][source.relative_to(library).as_posix()]:
                    raise ValueError('Copied index fingerprint mismatch')
        summaries = []
        with closing(sqlite3.connect(frozen / 'metadata.sqlite3')) as connection:
            with connection:
                for document in documents:
                    source = Path(document['file_path'])
                    source = (source if source.is_absolute() else library / source).resolve()
                    if not source.is_relative_to((library / 'papers').resolve()):
                        raise ValueError('PDF escapes the allowed papers directory')
                    if digest(source) != document['file_hash']:
                        raise ValueError('Source PDF fingerprint mismatch')
                    relative = 'papers/' + document['file_hash'] + '.pdf'
                    shutil.copy2(source, frozen / relative)
                    if digest(frozen / relative) != document['file_hash']:
                        raise ValueError('Copied PDF fingerprint mismatch')
                    connection.execute('UPDATE documents SET file_path=? WHERE id=?', (relative, document['id']))
                    summaries.append({k: document[k] for k in ['id', 'filename', 'file_hash', 'page_count', 'chunk_count']})
                    summaries[-1]['snapshot_path'] = relative
        if before != library_fingerprint(library) or configuration()[1] != config:
            raise ValueError('Library or configuration changed during snapshot; do not use this incomplete directory')
    archive = output / 'code.zip'
    git('archive', '--format=zip', '--output=' + str(archive), commit, '--',
        'backend', 'frontend', 'scripts', 'docs', '.gitignore', 'README.md')
    write_json(output / 'configuration.json', config)
    packages = sorted({(d.metadata['Name'], d.version) for d in importlib.metadata.distributions()})
    write_json(output / 'environment.json', {'python': sys.version, 'platform': platform.platform(),
                                           'packages': [{'name': name, 'version': version} for name, version in packages]})
    index_result = verify_index_on_copy(output)
    if git('rev-parse', 'HEAD') != commit or git('diff', '--name-only', 'HEAD', '--', *PRODUCT_PATHS):
        raise ValueError('Product source changed during snapshot; do not use this incomplete directory')
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
    manifest = {'schema_version': 1, 'baseline_id': output.name,
                'created_at': datetime.now(timezone.utc).isoformat(), 'source_commit': commit,
                'configuration': config, 'documents': summaries, 'chunk_count': chunks,
                'index_validation': index_result, 'files': files,
                'limitations': ['No evaluation questions or quality scores have been produced.',
                               'API keys and provider endpoint URLs are not included; reruns need private credentials.',
                               'Provider defaults, remote model updates and stochastic output cannot be frozen.',
                               'The offline probe checks stored vectors and local search, not live question answering.']}
    write_json(output / 'manifest.json', manifest)
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'verify', '_check-index'])
    parser.add_argument('path', type=Path)
    parser.add_argument('--check-index', action='store_true')
    args = parser.parse_args()
    if args.action == 'snapshot':
        result = snapshot(args.path)
    elif args.action == '_check-index':
        result = check_index(args.path)
    else:
        result = verify(args.path, args.check_index)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Configuration/provider errors can contain secrets; never print raw exception text.
        detail = str(error) if type(error) is ValueError else type(error).__name__
        print('Baseline operation failed: ' + detail, file=sys.stderr)
        sys.exit(1)
