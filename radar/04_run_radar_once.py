from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / "02_track_indiegogo_changes.py"
DASHBOARD_BUILDER = ROOT / "03_build_radar_dashboard.py"
DASHBOARD = ROOT / "AI众筹创新雷达_本地看板.html"
RUN_LOG = ROOT / "data" / "indiegogo" / "radar_run_log.csv"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_run_log(started_at: str, collection_status: str, dashboard_status: str, note: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    file_exists = RUN_LOG.exists() and RUN_LOG.stat().st_size > 0
    with RUN_LOG.open("a", encoding=("utf-8" if file_exists else "utf-8-sig"), newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["开始时间UTC", "结束时间UTC", "采集状态", "看板状态", "备注"])
        writer.writerow([started_at, now_utc(), collection_status, dashboard_status, note])


def run_stage(label: str, script: Path) -> None:
    if not script.exists():
        raise FileNotFoundError(f"找不到步骤文件：{script}")
    print(f"\n[{label}]", flush=True)
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, check=False)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, [sys.executable, str(script)])


def main() -> int:
    parser = argparse.ArgumentParser(description="采集Indiegogo项目、更新历史数据并生成本地看板")
    parser.add_argument(
        "--skip-collection",
        action="store_true",
        help="不访问网络，只用现有CSV重新生成看板，适合离线检查页面。",
    )
    args = parser.parse_args()

    started_at = now_utc()
    collection_status = "未开始"
    dashboard_status = "未开始"
    try:
        if args.skip_collection:
            collection_status = "跳过（离线重建）"
            print("离线重建模式：不访问众筹平台，只刷新本地看板。")
        else:
            run_stage("第1步：采集最新项目并更新历史快照", COLLECTOR)
            collection_status = "成功"

        run_stage("生成本地网页看板", DASHBOARD_BUILDER)
        if not DASHBOARD.exists() or DASHBOARD.stat().st_size == 0:
            raise RuntimeError("看板文件未生成或内容为空。")
        dashboard_status = "成功"
        append_run_log(started_at, collection_status, dashboard_status, "流程完成")
        print("\n整套流程已完成。")
        print(f"看板文件：{DASHBOARD}")
        print(f"运行记录：{RUN_LOG}")
        return 0
    except Exception as exc:
        append_run_log(started_at, collection_status, dashboard_status, f"失败：{type(exc).__name__}: {exc}")
        print(f"\n流程未完成：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
