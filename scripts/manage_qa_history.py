"""Export all local QA records or back up their independent SQLite database."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.literature import LiteratureSettings
from app.qa_history import HistoryStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'backup'])
    parser.add_argument('--database', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = (args.database or LiteratureSettings().root / 'qa_history.sqlite3').resolve()
    if not source.is_file():
        raise SystemExit('No QA history database exists yet.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    suffix = '.jsonl' if args.action == 'export' else '.sqlite3'
    output = (args.output or ROOT / 'backups' / f'qa_history_{stamp}{suffix}').resolve()
    if output == source or output.exists():
        raise SystemExit('Destination already exists; refusing to overwrite it.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.action == 'export':
        with output.open('x', encoding='utf-8', newline='\n') as handle:
            for line in HistoryStore(source).export():
                handle.write(line)
    else:
        # Reserve exclusively, then use SQLite's online backup to include committed WAL data.
        with output.open('xb'):
            pass
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
            with sqlite3.connect(output) as destination:
                original.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SystemExit('Backup verification failed.')
    print(f'{args.action} completed: {output}')


if __name__ == '__main__':
    main()
