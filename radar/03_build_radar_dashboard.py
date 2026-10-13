from __future__ import annotations

import csv
import html
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUTS = Path(__file__).resolve().parent
DATA = OUTPUTS / "data" / "indiegogo"
OUT = OUTPUTS / "AI众筹创新雷达_本地看板.html"


def read_csv(name: str) -> list[dict[str, str]]:
    path = DATA / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_num(value: str | float | None, digits: int = 0) -> str:
    parsed = num(str(value)) if value is not None else None
    if parsed is None:
        return "—"
    return f"{parsed:,.{digits}f}"


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def local_time(iso: str) -> str:
    if not iso:
        return "时间未知"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=8)))
        return dt.strftime("%Y年%m月%d日 %H:%M（北京时间）")
    except ValueError:
        return iso


def signed(value: str | float | None, digits: int = 0) -> str:
    parsed = num(str(value)) if value is not None else None
    if parsed is None:
        return "—"
    return f"{'+' if parsed >= 0 else ''}{parsed:,.{digits}f}"


def project_link(name: str, url: str) -> str:
    title = esc(name or "未命名项目")
    if url.startswith("https://"):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener">{title}<span class="link-mark">↗</span></a>'
    return title


snapshots = read_csv("indiegogo_snapshot_history.csv")
projects = read_csv("indiegogo_current_projects.csv")
backer_rank = read_csv("indiegogo_backer_growth_rank.csv")
goal_rank = read_csv("indiegogo_goal_progress_growth_rank.csv")
events = read_csv("indiegogo_change_events.csv")

latest_check = max((r.get("checked_at", "") for r in snapshots), default="")
latest_rows = [r for r in snapshots if r.get("checked_at") == latest_check] if latest_check else []
new_projects = [r for r in latest_rows if r.get("is_new_project") == "1"]
latest_events = [r for r in events if r.get("event_at") == latest_check]
intervals = [num(r.get("observation_interval_hours")) for r in latest_rows]
intervals = [x for x in intervals if x is not None and x > 0]
interval_hours = statistics.median(intervals) if intervals else None
interval_minutes = round(interval_hours * 60) if interval_hours is not None else None
changed_projects = len({r.get("project_id") for r in latest_events if r.get("project_id")})
project_by_id = {r.get("project_id"): r for r in projects}
current_sorted = sorted(projects, key=lambda r: num(r.get("backer_count")) or 0, reverse=True)

if interval_minutes is None:
    interval_label = "尚无有效间隔"
elif interval_minutes < 60:
    interval_label = f"约{interval_minutes}分钟"
else:
    interval_label = f"约{interval_hours:.1f}小时"

latest_label = local_time(latest_check)


def make_growth_rows(rows: list[dict[str, str]], kind: str) -> str:
    if not rows:
        return '<tr><td colspan="5" class="empty">本轮暂无满足该增长指标的项目。继续积累下一次快照后再观察。</td></tr>'
    result = []
    for row in rows[:10]:
        if kind == "backers":
            speed = fmt_num(row.get("每小时新增支持者人数"), 2) + " 人/小时"
            details = f"本周期 {signed(row.get('本周期新增支持者人数'))} 人 · 当前 {fmt_num(row.get('当前支持者人数'))} 人"
        else:
            speed = fmt_num(row.get("每小时目标进度增长百分点"), 2) + " 个百分点/小时"
            details = f"本周期 {signed(row.get('本周期目标进度变化百分点'), 2)} 个百分点 · 当前完成 {fmt_num(row.get('当前目标完成率百分比'), 2)}%"
        link = project_link(row.get("项目名称", ""), row.get("项目链接", ""))
        result.append(
            "<tr>"
            f"<td class=\"project-cell\">{link}<small>{esc(row.get('平台', 'Indiegogo'))}</small></td>"
            f"<td><strong>{esc(speed)}</strong><small>{esc(details)}</small></td>"
            f"<td>{esc(fmt_num(row.get('两次检查间隔小时'), 2))} 小时</td>"
            "</tr>"
        )
    return "\n".join(result)


def event_label(event_type: str) -> str:
    return {
        "backers_changed": "支持者人数变化",
        "funds_changed": "筹款金额变化",
        "status_changed": "项目状态变化",
        "project_discovered": "雷达新发现",
    }.get(event_type, event_type or "项目变化")


def event_rows() -> str:
    if not latest_events:
        return '<tr><td colspan="4" class="empty">本轮没有记录到可见变化。</td></tr>'
    result = []
    for row in latest_events[:12]:
        old = fmt_num(row.get("old_value"), 2)
        new = fmt_num(row.get("new_value"), 2)
        delta = signed(row.get("delta_value"), 2)
        kind = event_label(row.get("event_type", ""))
        if row.get("event_type") == "funds_changed":
            currency = project_by_id.get(row.get("project_id"), {}).get("currency", "")
            if currency:
                kind += f"（{currency}）"
        result.append(
            "<tr>"
            f"<td class=\"project-cell\">{project_link(row.get('project_name', ''), '')}</td>"
            f"<td>{esc(kind)}</td>"
            f"<td>{esc(old)} → {esc(new)}</td>"
            f"<td><strong>{esc(delta)}</strong></td>"
            "</tr>"
        )
    return "\n".join(result)


def popular_rows() -> str:
    if not current_sorted:
        return '<tr><td colspan="4" class="empty">还没有可展示的项目数据。</td></tr>'
    result = []
    for index, row in enumerate(current_sorted[:10], start=1):
        completion = num(row.get("goal_completion_pct"))
        completion_text = f"{completion:,.2f}%" if completion is not None else "—"
        status = row.get("status", "") or "未知"
        result.append(
            "<tr>"
            f"<td class=\"rank\">{index:02d}</td>"
            f"<td class=\"project-cell\">{project_link(row.get('project_name', ''), row.get('project_url', ''))}</td>"
            f"<td><strong>{esc(fmt_num(row.get('backer_count')))}</strong></td>"
            f"<td>{esc(completion_text)}</td>"
            f"<td><span class=\"status\">{esc(status)}</span></td>"
            "</tr>"
        )
    return "\n".join(result)


def discovered_rows() -> str:
    if not new_projects:
        return '<div class="empty-card"><span class="empty-icon">✓</span><div><strong>本轮没有新发现项目</strong><p>雷达会把“首次采集到”作为新发现，不代表项目刚刚上线。</p></div></div>'
    cards = []
    for row in new_projects[:8]:
        project = next((p for p in projects if p.get("project_id") == row.get("project_id")), {})
        cards.append(
            f'<article class="discovery">{project_link(row.get("project_name", ""), project.get("project_url", ""))}'
            f'<small>首次发现：{esc(local_time(row.get("checked_at", "")))}</small></article>'
        )
    return "".join(cards)


html_doc = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI众筹创新雷达｜本地看板</title>
<style>
:root{{--ink:#17324d;--muted:#6d8093;--blue:#1268a8;--cyan:#28a6bd;--line:#dce8f1;--paper:#f4f8fb;--white:#fff;--green:#13836f;--soft:#eaf4fa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;font-size:15px;line-height:1.55}}
.topbar{{background:linear-gradient(115deg,#123553,#176e9b 70%,#2b9aac);color:white;padding:28px max(24px,calc((100vw - 1180px)/2)) 25px;box-shadow:0 8px 24px #163d5718}}
.topline{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}h1{{font-size:30px;line-height:1.2;margin:0 0 8px;letter-spacing:.3px}}.subtitle{{margin:0;color:#d8edf6;font-size:15px}}.badge{{border:1px solid #ffffff66;background:#ffffff16;border-radius:99px;padding:8px 13px;font-size:13px;white-space:nowrap}}
main{{max-width:1180px;margin:0 auto;padding:22px 22px 48px}}.meta{{display:flex;gap:10px 22px;flex-wrap:wrap;color:var(--muted);font-size:14px;margin:0 0 16px}}.meta b{{color:var(--ink);font-weight:600}}
.notice{{background:#fff8e8;border:1px solid #f0dba7;border-left:4px solid #e4a83e;border-radius:10px;padding:12px 16px;margin-bottom:20px;color:#684e1d;font-size:14px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:23px}}.metric{{background:var(--white);border:1px solid var(--line);border-radius:14px;padding:18px 19px;box-shadow:0 3px 12px #183b5508}}.metric .label{{font-size:14px;color:var(--muted)}}.metric .value{{font-size:29px;font-weight:750;letter-spacing:-.5px;margin:5px 0 0;color:#135d8f}}.metric .hint{{font-size:12px;color:#8293a3;margin-top:2px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}}.panel{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px 19px;margin-bottom:18px;box-shadow:0 3px 12px #183b5508}}.grid2 .panel{{margin-bottom:0}}.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin:0 0 13px}}h2{{font-size:19px;margin:0;color:#1b405f}}.panel-desc{{font-size:13px;color:var(--muted);margin:4px 0 0}}.tag{{background:var(--soft);color:#176c94;border-radius:999px;padding:5px 9px;font-size:12px;white-space:nowrap}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:560px}}th{{text-align:left;color:#72869a;font-size:12px;font-weight:600;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}td{{padding:11px 8px;border-bottom:1px solid #edf2f6;vertical-align:top;font-size:14px}}tbody tr:last-child td{{border-bottom:0}}td small{{display:block;color:#8899a8;font-size:12px;margin-top:3px}}a{{color:#176b9c;text-decoration:none;font-weight:650}}a:hover{{text-decoration:underline}}.link-mark{{font-size:11px;margin-left:5px;color:#94a9b8}}.rank{{color:#93a5b4;font-weight:700}}.status{{display:inline-block;border-radius:99px;background:#e9f6f1;color:#168269;padding:3px 8px;font-size:12px}}.empty{{text-align:center;color:#8293a3;padding:20px!important}}.empty-card{{display:flex;align-items:center;gap:13px;padding:17px;background:#f7fbfd;border:1px dashed #ccdae5;border-radius:10px}}.empty-card p{{margin:3px 0 0;color:var(--muted);font-size:13px}}.empty-icon{{width:34px;height:34px;display:grid;place-items:center;background:#e5f5ef;border-radius:50%;color:var(--green);font-weight:800}}
.method{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.method-card{{background:#f6fafc;border:1px solid #e4edf3;border-radius:10px;padding:13px 14px}}.method-card strong{{display:block;color:#216584;margin-bottom:5px}}.method-card code{{font-family:Consolas,monospace;font-size:13px;color:#304e66;white-space:normal}}.footer{{color:#8798a6;text-align:center;font-size:12px;padding-top:12px}}
@media(max-width:800px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}.topbar{{padding:22px}}main{{padding:17px 14px 35px}}h1{{font-size:25px}}}}
@media(max-width:440px){{.cards{{grid-template-columns:1fr 1fr;gap:9px}}.metric{{padding:13px}}.metric .value{{font-size:24px}}.method{{grid-template-columns:1fr}}}}
@media print{{body{{background:white}}.topbar{{background:#175b83!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}.panel,.metric{{box-shadow:none;break-inside:avoid}}}}
</style>
</head>
<body>
<header class="topbar"><div class="topline"><div><h1>AI众筹创新雷达</h1><p class="subtitle">从公开项目数据中发现创意、观察变化、识别市场信号</p></div><span class="badge">模块一 · Indiegogo 监测原型</span></div></header>
<main>
<div class="meta"><span>最近采集：<b>{esc(latest_label)}</b></span><span>本轮实际间隔：<b>{esc(interval_label)}</b></span><span>数据平台：<b>Indiegogo</b></span></div>
<div class="notice">当前采集间隔约为{esc(interval_label)}，用于验证监测与指标计算流程；计划目标是每2小时检查一次，定时运行尚未配置。</div>
<section class="cards">
<div class="metric"><div class="label">当前监测项目</div><div class="value">{len(projects):,}</div><div class="hint">当前样本中的项目数量</div></div>
<div class="metric"><div class="label">本轮新发现</div><div class="value">{len(new_projects):,}</div><div class="hint">按雷达首次采集时间识别</div></div>
<div class="metric"><div class="label">本轮有变化项目</div><div class="value">{changed_projects:,}</div><div class="hint">支持者、筹款或状态出现变化</div></div>
<div class="metric"><div class="label">最近检查间隔</div><div class="value">{esc(interval_label)}</div><div class="hint">按两次实际采集时间计算</div></div>
</section>
<div class="grid2">
<section class="panel"><div class="panel-head"><div><h2>最近升温｜支持者增长</h2><p class="panel-desc">看最近一段时间新增支持者的速度</p></div><span class="tag">人 / 小时</span></div><div class="table-wrap"><table><thead><tr><th>项目</th><th>增长表现</th><th>观察间隔</th></tr></thead><tbody>{make_growth_rows(backer_rank, 'backers')}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>最近升温｜目标进度</h2><p class="panel-desc">看目标完成率最近上升的速度</p></div><span class="tag">百分点 / 小时</span></div><div class="table-wrap"><table><thead><tr><th>项目</th><th>增长表现</th><th>观察间隔</th></tr></thead><tbody>{make_growth_rows(goal_rank, 'goal')}</tbody></table></div></section>
</div>
<section class="panel"><div class="panel-head"><div><h2>雷达新发现</h2><p class="panel-desc">本轮第一次采集到的项目</p></div><span class="tag">发现 ≠ 刚上线</span></div>{discovered_rows()}</section>
<div class="grid2">
<section class="panel"><div class="panel-head"><div><h2>本轮项目变化</h2><p class="panel-desc">记录最近一次采集与上次采集之间的变化</p></div><span class="tag">{len(latest_events)} 条变化记录</span></div><div class="table-wrap"><table><thead><tr><th>项目</th><th>变化类型</th><th>上次 → 本次</th><th>变化量</th></tr></thead><tbody>{event_rows()}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>当前受欢迎程度｜支持者人数</h2><p class="panel-desc">按累计支持者人数排序，不混排不同币种金额</p></div><span class="tag">前10名</span></div><div class="table-wrap"><table><thead><tr><th>#</th><th>项目</th><th>支持者</th><th>目标完成率</th><th>状态</th></tr></thead><tbody>{popular_rows()}</tbody></table></div></section>
</div>
<section class="panel"><div class="panel-head"><div><h2>指标口径｜让判断可以解释、复核</h2><p class="panel-desc">“当前受欢迎”和“最近增长”分开观察，不合成为单一热度分数。</p></div></div><div class="method">
<div class="method-card"><strong>支持者增长速度</strong><code>本周期新增支持者人数 ÷ 实际检查间隔小时</code></div>
<div class="method-card"><strong>目标进度增长速度</strong><code>目标完成率变化百分点 ÷ 实际检查间隔小时</code></div>
<div class="method-card"><strong>当前受欢迎程度</strong><code>分别查看累计支持者人数、目标完成率；筹款金额不跨币种直接比较</code></div>
<div class="method-card"><strong>使用边界</strong><code>短周期变化是观察信号；项目热度不等于产品质量、市场成功或投资建议</code></div>
</div></section>
<div class="footer">本地原型看板 · 数据来自公开项目信息 · 每次采集后重新生成页面即可更新</div>
</main>
</body></html>'''

OUT.write_text(html_doc, encoding="utf-8")
print(f"看板已生成：{OUT}")
print(f"项目数：{len(projects)}；本轮新发现：{len(new_projects)}；变化项目：{changed_projects}；事件：{len(latest_events)}；间隔：{interval_label}")

