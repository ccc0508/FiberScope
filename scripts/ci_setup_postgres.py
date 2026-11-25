"""Bootstrap a PostgreSQL instance with V000-V012 migrations and Excel data imports."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WINDOWS_PSQL = Path(r"C:\Program Files\PostgreSQL\18\bin\psql.exe")


def _find_psql(explicit: str | None) -> str:
    if explicit:
        return explicit
    discovered = shutil.which("psql")
    if discovered:
        return discovered
    if DEFAULT_WINDOWS_PSQL.is_file():
        return str(DEFAULT_WINDOWS_PSQL)
    raise FileNotFoundError("Cannot locate psql executable")


def _run_psql(
    psql: str,
    *,
    host: str,
    port: int,
    user: str,
    database: str,
    password: str,
    sql_file: Path | None = None,
    sql_command: str | None = None,
) -> None:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    cmd = [
        psql,
        "-X",
        "-w",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
    ]
    if sql_file is not None:
        cmd.extend(["-f", str(sql_file)])
    elif sql_command is not None:
        cmd.extend(["-c", sql_command])
    else:
        raise ValueError("Provide either sql_file or sql_command")
    subprocess.run(cmd, check=True, env=env, cwd=PROJECT_ROOT)


def _run_migrations(
    psql: str,
    *,
    host: str,
    port: int,
    password: str,
    files: list[Path],
) -> None:
    for path in files:
        print(f"Applying {path.relative_to(PROJECT_ROOT)} ...")
        _run_psql(
            psql,
            host=host,
            port=port,
            user="postgres",
            database="plant_fiber_db",
            password=password,
            sql_file=path,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--importer-password", default="ci_importer_password")
    parser.add_argument("--reader-password", default="ci_reader_password")
    parser.add_argument("--app-password", default="ci_app_password")
    parser.add_argument("--psql", default=None)
    parser.add_argument("--env-out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    psql = _find_psql(args.psql)
    migrations_dir = PROJECT_ROOT / "database" / "migrations"
    bootstrap_dir = PROJECT_ROOT / "database" / "bootstrap"
    reports_dir = PROJECT_ROOT / "database" / "importer" / "reports"

    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="postgres",
        database="postgres",
        password=args.admin_password,
        sql_file=bootstrap_dir / "V000__roles.sql",
    )
    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="postgres",
        database="postgres",
        password=args.admin_password,
        sql_file=bootstrap_dir / "V000__database.sql",
    )
    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="postgres",
        database="postgres",
        password=args.admin_password,
        sql_command=(
            f"ALTER ROLE fiber_importer WITH PASSWORD '{args.importer_password}'; "
            f"ALTER ROLE fiber_reader WITH PASSWORD '{args.reader_password}';"
        ),
    )

    _run_migrations(
        psql,
        host=args.host,
        port=args.port,
        password=args.admin_password,
        files=[
            migrations_dir / "V001__create_core_tables.sql",
            migrations_dir / "V002__component_ratio_trigger.sql",
            migrations_dir / "V003__seed_reference_data.sql",
            migrations_dir / "V004__verify_schema.sql",
        ],
    )

    subprocess.run(
        [sys.executable, "database/importer/import_data.py", "--report-dir", str(reports_dir)],
        check=True,
        cwd=PROJECT_ROOT,
    )
    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="fiber_importer",
        database="plant_fiber_db",
        password=args.importer_password,
        sql_file=reports_dir / "formal_import_generated.sql",
    )

    _run_migrations(
        psql,
        host=args.host,
        port=args.port,
        password=args.admin_password,
        files=[
            migrations_dir / "V005__verify_imported_data.sql",
            migrations_dir / "V006__create_analysis_views.sql",
            migrations_dir / "V007__grant_and_verify_analysis_views.sql",
            migrations_dir / "V008__create_recycled_pulp_tables.sql",
            migrations_dir / "V009__create_recycled_pulp_views.sql",
        ],
    )

    recycled_sql = reports_dir / "recycled_summary_import_generated.sql"
    subprocess.run(
        [
            sys.executable,
            "database/importer/import_recycled_summary.py",
            "--sql-output",
            str(recycled_sql),
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )
    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="fiber_importer",
        database="plant_fiber_db",
        password=args.importer_password,
        sql_file=recycled_sql,
    )

    _run_migrations(
        psql,
        host=args.host,
        port=args.port,
        password=args.admin_password,
        files=[
            migrations_dir / "V010__verify_recycled_pulp_import.sql",
            migrations_dir / "V011__create_app_role.sql",
        ],
    )
    _run_psql(
        psql,
        host=args.host,
        port=args.port,
        user="postgres",
        database="plant_fiber_db",
        password=args.admin_password,
        sql_command=f"ALTER ROLE fiber_app WITH PASSWORD '{args.app_password}';",
    )
    _run_migrations(
        psql,
        host=args.host,
        port=args.port,
        password=args.admin_password,
        files=[migrations_dir / "V012__verify_complete_database.sql"],
    )

    args.env_out.parent.mkdir(parents=True, exist_ok=True)
    args.env_out.write_text(
        "\n".join(
            [
                f"PGHOST={args.host}",
                f"PGPORT={args.port}",
                "PGDATABASE=plant_fiber_db",
                "PGUSER=fiber_app",
                f"PGPASSWORD={args.app_password}",
                'CORS_ORIGINS=["http://127.0.0.1:4173","http://localhost:4173"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Database ready and env written to {args.env_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
