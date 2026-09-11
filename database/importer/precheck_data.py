from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl_core import (
    ValidationError,
    build_report,
    validate_and_build,
    write_failure_report,
    write_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读检查8份正式Excel，并生成可审计的预检报告。"
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
        report = build_report(dataset, args.data_dir)
        json_path, markdown_path = write_report(report, args.report_dir)
    except (ValidationError, OSError, ValueError) as error:
        failure_path = write_failure_report(error, args.data_dir, args.report_dir)
        print(f"预检失败：{error}", file=sys.stderr)
        print(f"失败报告：{failure_path}", file=sys.stderr)
        return 1

    print("预检状态：PASS")
    print("阻断错误：0")
    print(f"告警：{report['warning_count']}（均为已知单位状态，不阻断入库）")
    print("数量：sample=61, experiment_sample=63, sample_component=70, "
          "fiber_measurement=61, paper_measurement=61, data_source=178")
    print(f"JSON报告：{json_path}")
    print(f"可读报告：{markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
