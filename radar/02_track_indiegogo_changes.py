from __future__ import annotations

import csv
import json
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "indiegogo"
DB_PATH = DATA_DIR / "radar_history.sqlite3"
API_URL = "https://www.indiegogo.com/api/public/projects/getActiveCrowdfundingProjects"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def metrics(project: dict[str, Any], checked_at: str) -> dict[str, float | None]:
    goal = num(project.get("goal_amount"))
    raised = num(project.get("raised_amount"))
    backers = num(project.get("backer_count"))
    start = parse_dt(project.get("start_time"))
    checked = parse_dt(checked_at)
    elapsed_hours = None
    if start and checked:
        elapsed_hours = max((checked - start).total_seconds() / 3600, 0.0)
    return {
        "goal_completion_pct": (raised / goal * 100) if goal and goal > 0 and raised is not None else None,
        "average_pledge": (raised / backers) if backers and backers > 0 and raised is not None else None,
        "elapsed_hours": elapsed_hours,
        "raised_per_hour_since_launch": (raised / elapsed_hours) if elapsed_hours and elapsed_hours > 0 and raised is not None else None,
    }


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS projects (
            platform TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_name TEXT,
            project_url TEXT,
            short_description TEXT,
            category TEXT,
            creator_name TEXT,
            goal_amount REAL,
            raised_amount REAL,
            currency TEXT,
            backer_count INTEGER,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            image_url TEXT,
            comment_count INTEGER,
            update_count INTEGER,
            reward_count INTEGER,
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            goal_completion_pct REAL,
            average_pledge REAL,
            elapsed_hours REAL,
            raised_per_hour_since_launch REAL,
            PRIMARY KEY (platform, project_id)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            project_id TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            project_name TEXT,
            raised_amount REAL,
            backer_count INTEGER,
            status TEXT,
            goal_completion_pct REAL,
            average_pledge REAL,
            elapsed_hours REAL,
            raised_per_hour_since_launch REAL,
            raised_delta REAL,
            backer_delta INTEGER,
            raised_per_hour_between_checks REAL,
            observation_interval_hours REAL,
            goal_completion_delta_pp REAL,
            goal_progress_pp_per_hour REAL,
            backers_per_hour REAL,
            is_new_project INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            UNIQUE(platform, project_id, checked_at)
        );
        CREATE TABLE IF NOT EXISTS change_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            project_id TEXT NOT NULL,
            project_name TEXT,
            event_type TEXT NOT NULL,
            event_at TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            delta_value REAL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_project_time
            ON snapshots(platform, project_id, checked_at);
        CREATE INDEX IF NOT EXISTS idx_events_time ON change_events(event_at);
    """)
    # Existing databases are upgraded in place without deleting historical data.
    snapshot_columns = {row[1] for row in con.execute("PRAGMA table_info(snapshots)")}
    migrations = {
        "observation_interval_hours": "REAL",
        "goal_completion_delta_pp": "REAL",
        "goal_progress_pp_per_hour": "REAL",
        "backers_per_hour": "REAL",
    }
    for column, sql_type in migrations.items():
        if column not in snapshot_columns:
            con.execute(f"ALTER TABLE snapshots ADD COLUMN {column} {sql_type}")
    con.commit()
    return con


def export_csv(con: sqlite3.Connection) -> None:
    exports = {
        "indiegogo_current_projects.csv": """
            SELECT platform, project_id, project_name, project_url, category, creator_name,
                   goal_amount, raised_amount, currency, backer_count, status, start_time,
                   end_time, first_seen_at, last_checked_at, goal_completion_pct,
                   average_pledge, elapsed_hours, raised_per_hour_since_launch
            FROM projects ORDER BY backer_count DESC, goal_completion_pct DESC
        """,
        "indiegogo_snapshot_history.csv": """
            SELECT platform, project_id, project_name, checked_at, raised_amount, backer_count,
                   status, goal_completion_pct, average_pledge, elapsed_hours,
                   raised_per_hour_since_launch, raised_delta, backer_delta,
                   raised_per_hour_between_checks, observation_interval_hours,
                   goal_completion_delta_pp, goal_progress_pp_per_hour, backers_per_hour,
                   is_new_project
            FROM snapshots ORDER BY checked_at DESC, project_name
        """,
        "indiegogo_backer_growth_rank.csv": """
            SELECT p.platform AS 平台,
                   p.project_name AS 项目名称,
                   p.project_url AS 项目链接,
                   p.backer_count AS 当前支持者人数,
                   s.backer_delta AS 本周期新增支持者人数,
                   ROUND(s.backers_per_hour, 3) AS 每小时新增支持者人数,
                   p.goal_completion_pct AS 当前目标完成率百分比,
                   ROUND(s.goal_completion_delta_pp, 3) AS 本周期目标进度变化百分点,
                   ROUND(s.goal_progress_pp_per_hour, 3) AS 每小时目标进度增长百分点,
                   ROUND(s.observation_interval_hours, 3) AS 两次检查间隔小时,
                   s.checked_at AS 检查时间UTC
            FROM snapshots s
            JOIN projects p ON p.platform=s.platform AND p.project_id=s.project_id
            WHERE p.last_checked_at=s.checked_at
              AND s.is_new_project=0
              AND s.backers_per_hour > 0
            ORDER BY s.backers_per_hour DESC, s.backer_delta DESC
        """,
        "indiegogo_goal_progress_growth_rank.csv": """
            SELECT p.platform AS 平台,
                   p.project_name AS 项目名称,
                   p.project_url AS 项目链接,
                   p.currency AS 币种,
                   p.goal_completion_pct AS 当前目标完成率百分比,
                   ROUND(s.goal_completion_delta_pp, 3) AS 本周期目标进度变化百分点,
                   ROUND(s.goal_progress_pp_per_hour, 3) AS 每小时目标进度增长百分点,
                   p.backer_count AS 当前支持者人数,
                   s.backer_delta AS 本周期新增支持者人数,
                   ROUND(s.backers_per_hour, 3) AS 每小时新增支持者人数,
                   ROUND(s.observation_interval_hours, 3) AS 两次检查间隔小时,
                   s.checked_at AS 检查时间UTC
            FROM snapshots s
            JOIN projects p ON p.platform=s.platform AND p.project_id=s.project_id
            WHERE p.last_checked_at=s.checked_at
              AND s.is_new_project=0
              AND s.goal_progress_pp_per_hour > 0
            ORDER BY s.goal_progress_pp_per_hour DESC, s.goal_completion_delta_pp DESC
        """,
        "indiegogo_change_events.csv": """
            SELECT platform, project_id, project_name, event_type, event_at,
                   old_value, new_value, delta_value
            FROM change_events ORDER BY event_at DESC, project_name
        """,
    }
    for filename, sql in exports.items():
        rows = con.execute(sql).fetchall()
        path = DATA_DIR / filename
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows([dict(r) for r in rows])
            else:
                f.write("\n")


def seed_baseline_from_archives(con: sqlite3.Connection) -> int:
    """Import previously saved first-run samples, so the live fetch can be compared."""
    if con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] > 0:
        return 0
    files = sorted(DATA_DIR.glob("indiegogo_normalized_*.json"))
    seeded = 0
    for path in files:
        try:
            projects = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for project in projects:
            pid = project.get("project_id")
            checked_at = project.get("checked_at")
            if not pid or not checked_at:
                continue
            project = dict(project)
            m = metrics(project, checked_at)
            cur = con.execute("""
                INSERT OR IGNORE INTO snapshots
                (platform, project_id, checked_at, project_name, raised_amount, backer_count, status,
                 goal_completion_pct, average_pledge, elapsed_hours, raised_per_hour_since_launch,
                 raised_delta, backer_delta, raised_per_hour_between_checks, is_new_project, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1, ?)
            """, (
                project.get("platform", "Indiegogo"), pid, checked_at,
                project.get("project_name"), num(project.get("raised_amount")),
                int(num(project.get("backer_count")) or 0), project.get("status"),
                m["goal_completion_pct"], m["average_pledge"], m["elapsed_hours"],
                m["raised_per_hour_since_launch"], json.dumps(project, ensure_ascii=False),
            ))
            seeded += cur.rowcount
    con.commit()
    return seeded


def fetch_live() -> tuple[list[dict[str, Any]], str]:
    req = urllib.request.Request(API_URL, headers={
        "User-Agent": "AI-Crowdfunding-Radar/0.2 (teaching prototype)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    checked_at = iso_now()
    normalized: list[dict[str, Any]] = []
    for p in data:
        normalized.append({
            "platform": "Indiegogo",
            "project_id": p.get("projectUrlName"),
            "project_name": p.get("projectName"),
            "project_url": p.get("projectHomeUrl"),
            "short_description": p.get("shortDescription"),
            "category": None,
            "creator_name": p.get("creatorName"),
            "goal_amount": p.get("campaignGoal"),
            "raised_amount": p.get("fundsGathered"),
            "currency": p.get("currencyShortName"),
            "backer_count": p.get("backerCount"),
            "start_time": p.get("campaignStartDate"),
            "end_time": p.get("campaignEndDate"),
            "status": "active",
            "image_url": p.get("projectImageUrl"),
            "comment_count": p.get("commentCount"),
            "update_count": p.get("updateCount"),
            "reward_count": p.get("rewardCount"),
            "checked_at": checked_at,
        })
    return normalized, checked_at


def record_run(con: sqlite3.Connection, projects: list[dict[str, Any]], checked_at: str) -> dict[str, int]:
    counts = {"new": 0, "changed_funding": 0, "changed_backers": 0, "changed_status": 0, "unchanged": 0}
    for p in projects:
        platform, pid = p.get("platform", "Indiegogo"), p.get("project_id")
        if not pid:
            continue
        previous = con.execute("""
            SELECT * FROM snapshots WHERE platform=? AND project_id=?
            ORDER BY checked_at DESC, id DESC LIMIT 1
        """, (platform, pid)).fetchone()
        goal = num(p.get("goal_amount")); raised = num(p.get("raised_amount")); backers = int(num(p.get("backer_count")) or 0)
        m = metrics(p, checked_at)
        is_new = previous is None
        raised_delta = (raised - previous["raised_amount"]) if previous and raised is not None and previous["raised_amount"] is not None else None
        backer_delta = (backers - previous["backer_count"]) if previous else None
        hours_between = None
        if previous:
            dt0, dt1 = parse_dt(previous["checked_at"]), parse_dt(checked_at)
            if dt0 and dt1:
                hours_between = (dt1 - dt0).total_seconds() / 3600
        rate_between = raised_delta / hours_between if raised_delta is not None and hours_between and hours_between > 0 else None
        goal_completion_delta_pp = None
        if (previous and m["goal_completion_pct"] is not None
                and previous["goal_completion_pct"] is not None):
            goal_completion_delta_pp = m["goal_completion_pct"] - previous["goal_completion_pct"]
        goal_progress_pp_per_hour = (
            goal_completion_delta_pp / hours_between
            if goal_completion_delta_pp is not None and hours_between and hours_between > 0 else None
        )
        backers_per_hour = (
            backer_delta / hours_between
            if backer_delta is not None and hours_between and hours_between > 0 else None
        )

        con.execute("""
            INSERT OR IGNORE INTO snapshots
            (platform, project_id, checked_at, project_name, raised_amount, backer_count, status,
             goal_completion_pct, average_pledge, elapsed_hours, raised_per_hour_since_launch,
             raised_delta, backer_delta, raised_per_hour_between_checks,
             observation_interval_hours, goal_completion_delta_pp, goal_progress_pp_per_hour,
             backers_per_hour, is_new_project, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (platform, pid, checked_at, p.get("project_name"), raised, backers, p.get("status"),
              m["goal_completion_pct"], m["average_pledge"], m["elapsed_hours"], m["raised_per_hour_since_launch"],
              raised_delta, backer_delta, rate_between, hours_between if hours_between and hours_between > 0 else None,
              goal_completion_delta_pp, goal_progress_pp_per_hour, backers_per_hour,
              int(is_new), json.dumps(p, ensure_ascii=False)))

        if is_new:
            counts["new"] += 1
            con.execute("INSERT INTO change_events(platform,project_id,project_name,event_type,event_at,old_value,new_value,delta_value) VALUES (?,?,?,?,?,?,?,?)",
                        (platform,pid,p.get("project_name"),"new_project",checked_at,None,"first_seen",None))
        else:
            any_change = False
            if raised_delta is not None and abs(raised_delta) > 1e-9:
                counts["changed_funding"] += 1; any_change = True
                con.execute("INSERT INTO change_events(platform,project_id,project_name,event_type,event_at,old_value,new_value,delta_value) VALUES (?,?,?,?,?,?,?,?)",
                            (platform,pid,p.get("project_name"),"funds_changed",checked_at,str(previous["raised_amount"]),str(raised),raised_delta))
            if backer_delta is not None and backer_delta != 0:
                counts["changed_backers"] += 1; any_change = True
                con.execute("INSERT INTO change_events(platform,project_id,project_name,event_type,event_at,old_value,new_value,delta_value) VALUES (?,?,?,?,?,?,?,?)",
                            (platform,pid,p.get("project_name"),"backers_changed",checked_at,str(previous["backer_count"]),str(backers),float(backer_delta)))
            if previous["status"] != p.get("status"):
                counts["changed_status"] += 1; any_change = True
                con.execute("INSERT INTO change_events(platform,project_id,project_name,event_type,event_at,old_value,new_value,delta_value) VALUES (?,?,?,?,?,?,?,?)",
                            (platform,pid,p.get("project_name"),"status_changed",checked_at,str(previous["status"]),str(p.get("status")),None))
            if not any_change:
                counts["unchanged"] += 1

        first_seen = previous["checked_at"] if previous else checked_at
        values = {
            "platform": platform, "project_id": pid,
            "project_name": p.get("project_name"), "project_url": p.get("project_url"),
            "short_description": p.get("short_description"), "category": p.get("category"),
            "creator_name": p.get("creator_name"), "goal_amount": goal, "raised_amount": raised,
            "currency": p.get("currency"), "backer_count": backers, "start_time": p.get("start_time"),
            "end_time": p.get("end_time"), "status": p.get("status"), "image_url": p.get("image_url"),
            "comment_count": int(num(p.get("comment_count")) or 0), "update_count": int(num(p.get("update_count")) or 0),
            "reward_count": int(num(p.get("reward_count")) or 0), "first_seen_at": first_seen,
            "last_checked_at": checked_at, "goal_completion_pct": m["goal_completion_pct"],
            "average_pledge": m["average_pledge"], "elapsed_hours": m["elapsed_hours"],
            "raised_per_hour_since_launch": m["raised_per_hour_since_launch"],
        }
        cols = ",".join(values)
        placeholders = ",".join(["?"] * len(values))
        updates = ",".join(f"{k}=excluded.{k}" for k in values if k not in ("platform", "project_id", "first_seen_at"))
        con.execute(f"INSERT INTO projects ({cols}) VALUES ({placeholders}) ON CONFLICT(platform,project_id) DO UPDATE SET {updates}", tuple(values.values()))
    con.commit()
    return counts


def main() -> None:
    con = connect()
    seeded = seed_baseline_from_archives(con)
    projects, checked_at = fetch_live()
    counts = record_run(con, projects, checked_at)
    export_csv(con)
    print("AI众筹创新雷达｜采集与变化识别完成")
    print(f"检查时间（UTC）：{checked_at}")
    print(f"本次项目数：{len(projects)}")
    if seeded:
        print(f"已从之前保存的数据建立历史基线：{seeded}个项目")
    print(f"新增项目：{counts['new']}")
    print(f"筹款金额变化：{counts['changed_funding']}个")
    print(f"支持人数变化：{counts['changed_backers']}个")
    print(f"项目状态变化：{counts['changed_status']}个")
    print(f"未检测到上述变化：{counts['unchanged']}个")
    print(f"历史数据库：{DB_PATH}")
    print(f"可用WPS打开的当前项目表：{DATA_DIR / 'indiegogo_current_projects.csv'}")
    print(f"支持者增长榜：{DATA_DIR / 'indiegogo_backer_growth_rank.csv'}")
    print(f"目标进度增长榜：{DATA_DIR / 'indiegogo_goal_progress_growth_rank.csv'}")
    con.close()


if __name__ == "__main__":
    main()
