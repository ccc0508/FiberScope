"""Restore a backup to a NEW isolated cluster, never the existing database.

Requires local PostgreSQL binaries. Retains the cluster for inspection and API QA.
Local secrets and cluster files are written only under ignored tmp/.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backup', type=Path, required=True)
    p.add_argument('--pg-bin', type=Path, default=Path(r'C:\Program Files\PostgreSQL\18\bin'))
    p.add_argument('--port', type=int, default=55432)
    args = p.parse_args()
    if args.port == 5432:
        p.error('Port 5432 is reserved for the existing database')
    archive = args.backup.resolve(strict=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = Path(str(archive)+'.sha256.txt')
    if sidecar.exists():
        recorded = next((line.split('=',1)[1].strip().lower() for line in
                         sidecar.read_text(encoding='utf-8-sig').splitlines() if line.startswith('sha256=')), None)
        if recorded != digest:
            p.error('Backup SHA-256 does not match its saved record; no database was created')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    work = ROOT / 'tmp' / f'restore_{stamp}'
    work.mkdir(parents=True, exist_ok=False)
    password = secrets.token_urlsafe(32)
    pwfile = work / 'init-password.txt'
    pwfile.write_text(password, encoding='utf-8')
    env = dict(os.environ, PGPASSWORD=password, PGCLIENTENCODING='UTF8')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    def run(exe, *parts, input=None):
        if exe == 'pg_ctl':
            # On Windows the detached postgres child can inherit capture pipes.
            # Real files and a closed stdin prevent communicate() waiting forever.
            with (work / 'pg_ctl.log').open('a', encoding='utf-8') as log:
                result = subprocess.run([str(args.pg_bin / exe), *map(str, parts)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                    creationflags=flags, timeout=60)
            if result.returncode:
                raise RuntimeError('pg_ctl failed; inspect the isolated cluster log')
            return ''
        result = subprocess.run([str(args.pg_bin / exe), *map(str, parts)], input=input,
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                env=env, creationflags=flags, timeout=120)
        if result.returncode:
            # Database output does not contain the password-setting input on success.
            raise RuntimeError(f'{exe} failed: {result.stderr.replace(password, "[REDACTED]")}')
        return result.stdout

    cluster = work / 'cluster'
    run('initdb', '-D', cluster, '-U', 'postgres', '--encoding=UTF8', '--locale=C',
        '--auth=scram-sha-256', f'--pwfile={pwfile}')
    pwfile.unlink()
    run('pg_ctl', '-D', cluster, '-l', work / 'server.log', '-o',
        f'-h 127.0.0.1 -p {args.port}', '-w', 'start')
    conn = ['-X', '-w', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1', '-p', str(args.port), '-U', 'postgres']
    try:
        run('psql', *conn, '-d', 'postgres', '-f', ROOT / 'database/bootstrap/V000__roles.sql')
        run('psql', *conn, '-d', 'postgres', input="CREATE DATABASE plant_fiber_db TEMPLATE template0 ENCODING 'UTF8';\nALTER DATABASE plant_fiber_db SET timezone TO 'Asia/Shanghai';\nREVOKE ALL ON DATABASE plant_fiber_db FROM PUBLIC;\nGRANT CONNECT ON DATABASE plant_fiber_db TO fiber_owner, fiber_importer, fiber_reader;")
        run('pg_restore', '-w', '-h', '127.0.0.1', '-p', args.port, '-U', 'postgres',
            '-d', 'plant_fiber_db', '--exit-on-error', '--single-transaction', archive)
        for name in ['V005__verify_imported_data.sql', 'V010__verify_recycled_pulp_import.sql',
                     'V011__create_app_role.sql', 'V012__verify_complete_database.sql']:
            run('psql', *conn, '-d', 'plant_fiber_db', '-f', ROOT / 'database/migrations' / name)
        app_password = secrets.token_urlsafe(32)
        run('psql', *conn, '-d', 'plant_fiber_db', input=f"ALTER ROLE fiber_app PASSWORD '{app_password}';")
        (work / 'app.env').write_text(f'PGHOST=127.0.0.1\nPGPORT={args.port}\nPGDATABASE=plant_fiber_db\nPGUSER=fiber_app\nPGPASSWORD={app_password}\n', encoding='utf-8')
        (work / 'admin.env').write_text(f'PGHOST=127.0.0.1\nPGPORT={args.port}\nPGDATABASE=plant_fiber_db\nPGUSER=postgres\nPGPASSWORD={password}\n', encoding='utf-8')
        report = dict(status='PASS', started_at=stamp, verified_at=datetime.now(timezone.utc).isoformat(), backup=archive.name,
                      sha256=digest,
                      postgres_version=run('postgres', '--version').strip(),
                      checks=['archive_restore', 'V005', 'V010', 'V011', 'V012'],
                      cluster=str(cluster), port=args.port, app_env=str(work / 'app.env'))
        (work / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    except Exception:
        run('pg_ctl', '-D', cluster, '-m', 'fast', '-w', 'stop')
        raise


if __name__ == '__main__':
    main()
