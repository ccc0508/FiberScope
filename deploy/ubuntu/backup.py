"""Local protected backup of the experiment DB, QA stores, PDFs and service settings."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

from filelock import FileLock

DATA = Path('/var/lib/fiberscope/rag-data')
BACKUPS = Path('/var/backups/fiberscope')
SQLITE_FILES = ['metadata.sqlite3', 'qa_history.sqlite3', 'extraction/records.sqlite3', 'chroma/chroma.sqlite3']


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    import os
    os.umask(0o077)
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = BACKUPS / stamp
    output.mkdir(mode=0o700)
    for arguments, name in [(['pg_dump', '-Fc', 'plant_fiber_db'], 'database.dump'),
                            (['pg_dumpall', '--roles-only'], 'roles.sql')]:
        with (output / name).open('xb') as handle:
            result = subprocess.run(['runuser', '-u', 'postgres', '--', *arguments],
                                    stdout=handle, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError('Database backup failed')
    with FileLock(str(DATA / '.import.lock'), timeout=30):
        with tempfile.TemporaryDirectory(prefix='staging-', dir=output) as temporary:
            working = Path(temporary)
            for source in DATA.rglob('*'):
                relative = source.relative_to(DATA)
                if not source.is_file() or relative.as_posix() in SQLITE_FILES or source.name.endswith(('-wal', '-shm', '.lock')):
                    continue
                if source.is_symlink():
                    raise RuntimeError('Unexpected data symlink')
                destination = working / 'rag-data' / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for relative in SQLITE_FILES:
                destination = working / 'rag-data' / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect((DATA / relative).as_uri() + '?mode=ro', uri=True)) as original:
                    with closing(sqlite3.connect(destination)) as target:
                        original.backup(target)
                        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise RuntimeError('SQLite backup integrity failed')
            shutil.copytree('/etc/fiberscope', working / 'settings')
            with tarfile.open(output / 'records-and-settings.tar.gz', 'w:gz') as archive:
                archive.add(working / 'rag-data', arcname='rag-data')
                archive.add(working / 'settings', arcname='settings')
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'PostgreSQL, roles, SQLite stores, PDFs, vectors, checkpoints and private service settings',
                'files': {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    # Prune only complete snapshots created by this tool, within the fixed backup root.
    completed = sorted(p for p in BACKUPS.iterdir() if p.is_dir() and len(p.name) == 16
                       and p.name.endswith('Z') and (p / 'manifest.json').is_file())
    for old in completed[:-14]:
        if old.resolve().parent != BACKUPS.resolve():
            raise RuntimeError('Backup path escapes root')
        shutil.rmtree(old)
    print(json.dumps({'backup': str(output), 'checksums': 'saved', 'retention': 14}))


if __name__ == '__main__':
    main()
