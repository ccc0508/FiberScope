from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

from recycled_summary_core import RecycledImportError, generate_import_sql, validate_and_build


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PSQL = Path(r"C:\Program Files\PostgreSQL\18\bin\psql.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成数据汇总工作簿的增量入库SQL；只有--apply才写入数据库。"
    )
    parser.add_argument("--apply", action="store_true", help="正式连接PostgreSQL并执行导入。")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument(
        "--sql-output",
        type=Path,
        default=Path(__file__).resolve().parent / "reports" / "recycled_summary_import_generated.sql",
    )
    parser.add_argument("--psql", type=Path, default=DEFAULT_PSQL)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="plant_fiber_db")
    parser.add_argument("--user", default="fiber_importer")
    return parser.parse_args()


def _run_psql(args: argparse.Namespace, sql_path: Path, password: str) -> None:
    if args.user != "fiber_importer":
        raise RecycledImportError("正式业务数据必须使用fiber_importer账号导入")
    if not args.psql.is_file():
        raise RecycledImportError(f"找不到psql：{args.psql}")

    environment = os.environ.copy()
    environment["PGPASSWORD"] = password
    command = [
        str(args.psql),
        "-X",
        "-w",
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
    ]
    subprocess.run(command, check=True, env=environment)


def main() -> int:
    args = parse_args()
    try:
        dataset = validate_and_build(args.data_dir)
        sql_text = generate_import_sql(dataset)
        args.sql_output.parent.mkdir(parents=True, exist_ok=True)
        args.sql_output.write_text(sql_text, encoding="utf-8")
    except (RecycledImportError, OSError, ValueError) as error:
        print(f"生成失败：{error}", file=sys.stderr)
        return 1

    print(f"SQL预览已生成：{args.sql_output}")
    if not args.apply:
        print("当前为预览模式，数据库未被修改。")
        return 0

    confirmation = input("请输入大写 IMPORT_RECYCLED 确认正式写入：").strip()
    if confirmation != "IMPORT_RECYCLED":
        print("确认词不匹配，未连接数据库。")
        return 2

    password = getpass.getpass("请输入fiber_importer的PostgreSQL密码：")
    try:
        _run_psql(args, args.sql_output, password)
    except (RecycledImportError, subprocess.CalledProcessError) as error:
        print(f"正式导入失败：{error}", file=sys.stderr)
        return 1
    finally:
        password = ""

    print("正式导入事务执行成功。请使用fiber_reader运行V010验收。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
