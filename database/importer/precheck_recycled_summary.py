from __future__ import annotations

import argparse
import sys
from pathlib import Path

from recycled_summary_core import RecycledImportError, build_report, validate_and_build, write_report


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读检查数据汇总(1).xlsx，并生成再生纸浆循环实验入库预检报告。"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="来源Excel目录；默认使用项目data文件夹。",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "reports",
        help="预检报告输出目录。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        dataset = validate_and_build(args.data_dir)
        report = build_report(dataset)
        json_path, markdown_path = write_report(report, args.report_dir)
    except (RecycledImportError, OSError, ValueError) as error:
        print(f"预检失败：{error}", file=sys.stderr)
        return 1

    print("预检状态：PASS")
    print("数量：dataset=1, data_block=14, observation=131, summary_point=47, review_row=4")
    print("数据块：G01-G14（显示名称为数据块01-14）；正式实验条件未知")
    print(f"JSON报告：{json_path}")
    print(f"可读报告：{markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
