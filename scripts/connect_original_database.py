"""Connect the backend to the original database with a locally entered password.

This script never changes experimental data. It verifies and backs up the database,
creates fiber_app only when absent, and refuses to replace an existing backend/.env.
Run with the project's virtual environment in an interactive terminal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / 'database' / 'migrations'


def migration_body(name: str) -> str:
    """Remove only psql directives and outer transaction commands.

    The caller owns the transaction; internal PL/pgSQL BEGIN/END remain intact.
    """
    lines = (MIGRATIONS / name).read_text(encoding='utf-8-sig').splitlines()
    return '\n'.join(line for line in lines if not line.startswith('\\')
        and line.strip().upper() not in ('BEGIN;', 'BEGIN READ ONLY;', 'BEGIN TRANSACTION READ ONLY;', 'COMMIT;'))


def backup(pg_bin: Path, connection: dict, password: str, stamp: str) -> Path:
    directory = ROOT / 'backups'
    directory.mkdir(exist_ok=True)
    path = directory / f'plant_fiber_db_before_app_{stamp}.dump'
    if path.exists():
        raise RuntimeError('Backup target already exists')
    environment = dict(os.environ, PGPASSWORD=password, PGCLIENTENCODING='UTF8')
    args = ['-h',connection['host'],'-p',str(connection['port']),'-U',connection['user']]
    result = subprocess.run([str(pg_bin / 'pg_dump.exe'), *args, '-w', '-Fc',
        '-f', str(path), connection['dbname']], env=environment, capture_output=True)
    if result.returncode:
        raise RuntimeError('Backup failed; no application role was changed')
    result = subprocess.run([str(pg_bin / 'pg_restore.exe'),'--list',str(path)],capture_output=True)
    if result.returncode:
        raise RuntimeError('Backup cannot be read; no application role was changed')
    Path(str(path)+'.restore-list.txt').write_bytes(result.stdout)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path)+'.sha256.txt').write_text(f'file={path.name}\nsha256={digest}\n',encoding='utf-8')
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1','localhost'])
    parser.add_argument('--port',type=int,default=5432,choices=[5432])
    parser.add_argument('--pg-bin',type=Path,default=Path(r'C:\Program Files\PostgreSQL\18\bin'))
    args = parser.parse_args()
    destination = ROOT / 'backend' / '.env'
    if destination.exists():
        parser.error('backend/.env already exists; refusing to replace existing configuration')
    for exe in ['pg_dump.exe','pg_restore.exe']:
        if not (args.pg_bin / exe).is_file():
            parser.error(f'Missing PostgreSQL tool: {exe}')
    if not sys.stdin.isatty():
        parser.error('Run in an interactive terminal so the password can be entered without echo')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report_path = ROOT / 'tmp' / f'original_connection_{stamp}.json'
    report_path.parent.mkdir(exist_ok=True)
    connection = dict(host=args.host,port=args.port,dbname='plant_fiber_db',user='postgres',connect_timeout=5)
    print('Target: local PostgreSQL port 5432 / plant_fiber_db')
    admin_password = getpass.getpass('PostgreSQL postgres password (hidden): ')
    app_password = ''
    report = dict(status='STARTED', target='original database on port 5432', checks=[])
    try:
        with psycopg.connect(**connection,password=admin_password,autocommit=True) as admin:
            with admin.transaction():
                admin.execute("SET TRANSACTION READ ONLY")
                admin.execute("SET LOCAL timezone TO 'Asia/Shanghai'")
                admin.execute('SET LOCAL statement_timeout=30000')
                for name in ['V005__verify_imported_data.sql','V010__verify_recycled_pulp_import.sql']:
                    admin.execute(migration_body(name))
                    report['checks'].append(name)
                exists = admin.execute("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='fiber_app')").fetchone()[0]
            print('PASS: original core and recycled data verification')
            if exists:
                # Do not reset or change a manually created role or its password.
                app_password = getpass.getpass('Existing fiber_app password (hidden; will not be reset): ')
                with psycopg.connect(**dict(connection,user='fiber_app'),password=app_password) as existing:
                    existing.execute('SELECT 1')
            else:
                report['backup'] = backup(args.pg_bin,connection,admin_password,stamp).name
                print('PASS: pre-change backup and archive readability')
                app_password = secrets.token_urlsafe(32)
            with admin.transaction():
                admin.execute('SET LOCAL statement_timeout=30000')
                if not exists:
                    admin.execute(migration_body('V011__create_app_role.sql'))
                    admin.execute(sql.SQL('ALTER ROLE fiber_app PASSWORD {}').format(sql.Literal(app_password)))
                admin.execute(migration_body('V012__verify_complete_database.sql'))
                # Write credentials before commit; if the transaction fails, remove only
                # the configuration this invocation created, never any pre-existing file.
                with destination.open('x',encoding='utf-8') as env_file:
                    env_file.write(f'PGHOST={args.host}\nPGPORT={args.port}\nPGDATABASE=plant_fiber_db\nPGUSER=fiber_app\nPGPASSWORD={json.dumps(app_password)}\n')
                report['config_created'] = True
            report['role_ready'] = True
            report['role_action'] = 'verified_existing' if exists else 'created_V011'
            report['checks'].append('V012__verify_complete_database.sql')
        with psycopg.connect(**dict(connection,user='fiber_app'),password=app_password) as app:
            actual = app.execute('SELECT count(*) FROM fiber.v_sample_overview').fetchone()[0]
            if actual != 61:
                raise RuntimeError('Application sample count mismatch')
        print('PASS: fiber_app connection and 61 samples')
        environment = dict(os.environ)
        for key in ['PGHOST','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','CORS_ORIGINS']:
            environment.pop(key,None)
        environment['TEST_DB_ENV'] = str(destination)
        tests = subprocess.run([sys.executable,'-m','pytest','-q'],cwd=ROOT/'backend',env=environment)
        if tests.returncode:
            raise RuntimeError('Backend integration tests failed; inspect test output')
        report['checks'].append('backend_integration_tests')
        report['status'] = 'PASS'
        print('PASS: original database connected, verified, and backend tests passed')
        return 0
    except Exception as error:
        if report.get('config_created') and not report.get('role_ready'):
            destination.unlink(missing_ok=True)
        report['status'] = 'FAILED'
        report['error_type'] = type(error).__name__
        # Never echo SQL/connection exceptions, which may contain a password literal.
        print(f'Failed ({type(error).__name__}). No experimental data was changed. Check local connection or validation results.')
        return 1
    finally:
        admin_password = app_password = ''
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(f'Result (no passwords): {report_path}')


if __name__ == '__main__':
    raise SystemExit(main())
