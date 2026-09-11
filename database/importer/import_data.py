from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from etl_core import (
    ValidationError,
    build_report,
    generate_import_sql,
    validate_and_build,
    write_failure_report,
    write_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PSQL = Path(r"C:\Program Files\PostgreSQL\18\bin\psql.exe")


def _default_psql() -> str:
    discovered = shutil.which("psql")
    if discovered:
        return discovered
    return str(DEFAULT_PSQL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="预检并生成正式入库SQL；只有带--apply时才连接PostgreSQL。"
    )
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "reports",
    )
    parser.add_argument("--psql", default=_default_psql(), help="psql.exe完整路径")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="plant_fiber_db")
    parser.add_argument("--user", default="fiber_importer")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="正式连接数据库并执行导入；省略时只生成SQL预览。",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="与--apply同时使用时跳过IMPORT文字确认。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        dataset = validate_and_build(args.data_dir)
        report = build_report(dataset, args.data_dir)
        write_report(report, args.report_dir)
        sql_text = generate_import_sql(dataset)
    except (ValidationError, OSError, ValueError) as error:
        failure_path = write_failure_report(error, args.data_dir, args.report_dir)
        print(f"预检失败，未连接数据库：{error}", file=sys.stderr)
        print(f"失败报告：{failure_path}", file=sys.stderr)
        return 1

    args.report_dir.mkdir(parents=True, exist_ok=True)
    sql_path = args.report_dir / "formal_import_generated.sql"
    sql_path.write_text(sql_text, encoding="utf-8")
    print("8份正式Excel预检通过。")
    print(f"已生成入库SQL：{sql_path}")

    if not args.apply:
        print("当前为安全预览模式：没有连接或修改数据库。")
        print("确认后使用 --apply 执行正式入库。")
        return 0

    if args.database != "plant_fiber_db":
        print("拒绝执行：正式入库数据库必须是plant_fiber_db。", file=sys.stderr)
        return 2
    if args.user != "fiber_importer":
        print("拒绝执行：正式入库必须使用fiber_importer账号。", file=sys.stderr)
        return 2

    psql_path = Path(args.psql)
    if not psql_path.is_file() and shutil.which(args.psql) is None:
        print(f"找不到psql：{args.psql}", file=sys.stderr)
        return 2

    if not args.yes:
        confirmation = input(
            "即将向plant_fiber_db写入正式实验数据。请输入IMPORT继续："
        ).strip()
        if confirmation != "IMPORT":
            print("已取消，没有修改数据库。")
            return 0

    verify_path = PROJECT_ROOT / "database" / "migrations" / "V005__verify_imported_data.sql"
    if not verify_path.is_file():
        print(f"缺少验收脚本：{verify_path}", file=sys.stderr)
        return 2

    command = [
        args.psql,
        "-X",
        "-W",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        args.host,
        "-p",
        str(args.port),
        "-U",
        args.user,
        "-d",
        args.database,
        "-f",
        str(sql_path),
        "-f",
        str(verify_path),
    ]
    environment = os.environ.copy()
    environment["PGCLIENTENCODING"] = "UTF8"
    completed = subprocess.run(command, env=environment, check=False)
    if completed.returncode != 0:
        print(
            "正式入库或V005验收失败。入库脚本中的写入位于单一事务内；"
            "请根据上方第一条ERROR处理。",
            file=sys.stderr,
        )
        return completed.returncode

    print("正式入库与V005验收均已通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
