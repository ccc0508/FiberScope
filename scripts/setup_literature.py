"""Copy an existing SRP literature library and its selected settings, without re-embedding."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from dotenv import dotenv_values
from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
KEYS = ['EMBEDDING_PROVIDER','EMBEDDING_MODEL','EMBEDDING_DIMENSIONS','EMBEDDING_API_KEY',
        'EMBEDDING_BASE_URL','LLM_PROVIDER','LLM_MODEL','LLM_API_KEY','LLM_BASE_URL','TOP_K','MIN_SCORE']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    target = ROOT / '.rag-data'
    environment = ROOT / 'backend' / '.env.literature'
    if target.exists() or environment.exists():
        raise SystemExit('Destination already exists; refusing to overwrite the current library or settings.')
    settings = dotenv_values(source / '.env')
    raw_dir = Path(settings.get('RAG_DATA_DIR') or '.rag-data')
    library = (source / raw_dir).resolve()
    if not (library / 'metadata.sqlite3').is_file() or not (library / 'chroma').is_dir():
        raise SystemExit('Source library is missing.')
    # Cooperates with the original importer; queries may continue reading its library.
    with FileLock(str(library / '.import.lock'), timeout=10):
        target.mkdir()
        with sqlite3.connect((library / 'metadata.sqlite3').as_uri()+'?mode=ro', uri=True) as original:
            with sqlite3.connect(target / 'metadata.sqlite3') as destination:
                original.backup(destination)
        shutil.copytree(library / 'chroma', target / 'chroma')
        # SQLite backup includes any committed WAL data, instead of copying database pages alone.
        with sqlite3.connect((library / 'chroma/chroma.sqlite3').as_uri()+'?mode=ro', uri=True) as original:
            with sqlite3.connect(target / 'chroma/chroma.sqlite3') as destination:
                original.backup(destination)
        (target / 'papers').mkdir()
        with sqlite3.connect(target / 'metadata.sqlite3') as conn:
            rows = conn.execute("SELECT id,file_path,file_hash FROM documents WHERE status='completed'").fetchall()
            for document_id, raw_path, digest in rows:
                pdf = Path(raw_path)
                if not pdf.is_absolute():
                    pdf = source / pdf
                if hashlib.sha256(pdf.read_bytes()).hexdigest() != digest:
                    raise SystemExit('Source PDF changed; snapshot aborted. No model calls or credential writes made.')
                # A generated safe filename prevents source path names from escaping the target.
                name = hashlib.sha256(document_id.encode()).hexdigest() + '.pdf'
                shutil.copy2(pdf, target / 'papers' / name)
                conn.execute('UPDATE documents SET file_path=? WHERE id=?', ('papers/'+name, document_id))
    lines = ['LITERATURE_ENABLED=true','LITERATURE_DATA_DIR=../.rag-data','LITERATURE_TIMEOUT_SECONDS=90']
    for key in KEYS:
        value = settings.get('RAG_'+key)
        if value is not None:
            # JSON strings are accepted by dotenv; no values are printed or placed in commands.
            lines.append('RAG_'+key+'='+json.dumps(value, ensure_ascii=False))
    environment.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(f'Copied {len(rows)} completed documents and the existing vector index. Private settings saved locally.')


if __name__ == '__main__':
    main()
