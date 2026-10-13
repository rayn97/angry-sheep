from __future__ import annotations

import csv
import html
import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "indiegogo"
DB = DATA / "radar_history.sqlite3"
OUT = ROOT / "AI众筹创新雷达_本地看板.html"


def read_csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_history():
    if not DB.exists():
        return [], [], []
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        projects = [dict(x) for x in con.execute("SELECT * FROM projects")]
        snapshots = [dict(x) for x in con.execute("SELECT * FROM snapshots")]
        events = [dict(x) for x in con.execute("SELECT * FROM change_events ORDER BY event_at DESC, project_name")]
    finally:
        con.close()
    by_id = {x.get("project_id"): x for x in projects}
    # 项目表只保存当前数值；项目简介等文本字段从最近一次快照的 payload 补回，供方向识别使用。
    latest_payload = {}
    for row in snapshots:
        pid = row.get("project_id")
        if pid and (pid not in latest_payload or str(row.get("checked_at") or "") > str(latest_payload[pid].get("checked_at") or "")):
            try:
                latest_payload[pid] = {"checked_at": row.get("checked_at"), **json.loads(row.get("payload_json") or "{}")}
            except (TypeError, json.JSONDecodeError):
                pass
    for pid, payload in latest_payload.items():
        if pid in by_id:
            for key in ("project_url", "short_description", "category", "currency", "image_url"):
                if payload.get(key) and not by_id[pid].get(key):
                    by_id[pid][key] = payload[key]
    for row in snapshots:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        project = by_id.get(row.get("project_id"), {})
        for key in ("project_url", "short_description", "category", "currency", "image_url"):
            row[key] = payload.get(key) or project.get(key) or ""
    return projects, snapshots, events


def number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def fmt(value, digits=0):
    n = number(value)
    return "—" if n is None else f"{n:,.{digits}f}"


def signed(value, digits=0):
    n = number(value)
    return "—" if n is None else f"{'+' if n >= 0 else ''}{n:,.{digits}f}"


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def local_time(value, short=False):
    if not value:
        return "时间未知"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=8)))
        return dt.strftime("%m月%d日 %H:%M" if short else "%Y年%m月%d日 %H:%M（北京时间）")
    except ValueError:
        return str(value)


def link(name, url):
    title = esc(name or "未命名项目")
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{title}<span class="link-mark">↗</span></a>' if str(url or "").startswith("https://") else title


# 采用可解释的关键词规则识别项目方向，便于学生检查和修订分类结果。
# “项目方向”描述众筹样本中的创意主题，不等同于官方行业分类。
CLASSIFIERS = [
    ("人工智能与智能硬件", [("人工智能", r"\b(ai|artificial intelligence|machine learning|chatgpt)\b"), ("机器人", r"\b(robot|robotics|humanoid)\b"), ("智能设备", r"\b(smart home|smart device|wearable|sensor|drone)\b")]),
    ("消费电子与数码", [("手机电脑", r"\b(phone|smartphone|tablet|laptop|computer)\b"), ("影音摄影", r"\b(camera|headphones?|earbuds?|speaker|microphone)\b"), ("游戏数码", r"\b(gaming|keyboard|monitor|console)\b")]),
    ("健康与运动", [("健康医疗", r"\b(health|medical|therapy|wellness|sleep|dental|mental health)\b"), ("运动健身", r"\b(fitness|yoga|cycling|running|training|athlete|sport)\b")]),
    ("影视、音乐与游戏", [("音乐", r"\b(music|musical|album|vinyl|song|band|symphonic|concert|musician)\b"), ("影视", r"\b(film|filmmaker|movie|cinema|cine|pel[ií]cula|documentary|video|television|tv show|series|pilot|screenplay|actress|actor|director|animation|theatre|theater)\b"), ("游戏动漫", r"\b(game|gaming|comic|anime)\b")]),
    ("生活方式与家居", [("家居生活", r"\b(home|house|kitchen|furniture|garden|coffee|renovation|lamp|table)\b"), ("食品饮品", r"\b(food|drink|beer|wine|cooking|tea|restaurant|cafe)\b"), ("服饰用品", r"\b(fashion|clothing|shoes?|backpack|jewelry|leather|cosmetic|fragrance|perfume)\b")]),
    ("出行、环保与能源", [("出行交通", r"\b(bike|bicycle|electric vehicle|vehicle|motorcycle|automotive|roadster|mobility|transportation|vessel|marine|workboat|train|tram)\b"), ("环保能源", r"\b(solar|energy|sustainable|eco[- ]friendly|recycl\w*|zero[- ]emission)\b"), ("户外旅行", r"\b(outdoor|camping|travel|adventure)\b")]),
    ("教育与知识", [("教育学习", r"\b(education|learning|course|textbook|knowledge|guide|tutorial)\b")]),
    ("艺术与出版", [("艺术创作", r"\b(artist|artwork|art installation|exhibition|sculpture|painting|gallery|residency|photography)\b"), ("图书出版", r"\b(book|novel|magazine|publication|publishing|poetry|poet|writer|author|graphic novel)\b"), ("手工与设计", r"\b(ceramic|pottery|craft|handmade|design collection|printmaking)\b")]),
    ("社区与公共文化", [("社区项目", r"\b(community|neighborhood|village|local community|community hub)\b"), ("公益与援助", r"\b(nonprofit|charity|donation|fundraiser|clean water|public school|children in need|rescue)\b"), ("文化传承", r"\b(cultural heritage|history|museum|ancestral|tradition|indigenous)\b")]),
    ("数字产品与软件", [("软件应用", r"\b(app|application|software|saas|digital platform|mobile platform)\b"), ("在线服务", r"\b(streaming platform|online service|subscription service|marketplace|language translation)\b")]),
    ("制造与工程", [("先进制造", r"\b(3d printer|3d printing|manufacturing|injection molding|engineering|industrial design)\b"), ("工具与设备", r"\b(tool|pump|water well|mechanical|ejector|filament)\b")]),
]


def classify(row):
    text = " ".join(str(row.get(k) or "") for k in ("project_name", "short_description", "category")).lower()
    best, tags, score = "其他创意项目", ["待进一步识别"], 0
    for sector, rules in CLASSIFIERS:
        matched = [label for label, pattern in rules if re.search(pattern, text, re.I)]
        if len(matched) > score:
            best, tags, score = sector, matched, len(matched)
    return best, tags


projects, snapshots, events = read_history()
if not projects:
    projects = read_csv("indiegogo_current_projects.csv")
if not snapshots:
    snapshots = read_csv("indiegogo_snapshot_history.csv")
if not events:
    events = read_csv("indiegogo_change_events.csv")

by_id = {r.get("project_id"): r for r in projects}
classes = {pid: classify(row) for pid, row in by_id.items()}
latest = max((str(r.get("checked_at") or "") for r in snapshots), default="")
latest_rows = [r for r in snapshots if str(r.get("checked_at") or "") == latest]
new_rows = [r for r in latest_rows if str(r.get("is_new_project")) == "1"]
latest_events = [r for r in events if str(r.get("event_at") or "") == latest]
intervals = [number(r.get("observation_interval_hours")) for r in latest_rows]
intervals = [x for x in intervals if x and x > 0]
interval_hours = statistics.median(intervals) if intervals else None
interval_mins = round(interval_hours * 60) if interval_hours else None
interval_label = "暂无有效间隔" if interval_mins is None else (f"约{interval_mins}分钟" if interval_mins < 60 else f"约{interval_hours:.1f}小时")


def project_for(row):
    result = dict(by_id.get(row.get("project_id"), {}))
    result.update({k: v for k, v in row.items() if v not in (None, "")})
    return result


def meta(row, with_keywords=False):
    sector, tags = classes.get(row.get("project_id"), classify(row))
    words = f" 关键词：{'、'.join(tags[:3])}" if with_keywords else ""
    return f'<small class="project-meta"><span class="chip">{esc(sector)}</span>{esc(words)}</small>'


def ranking(kind):
    result = []
    for snapshot in latest_rows:
        if str(snapshot.get("is_new_project")) == "1":
            continue
        p = project_for(snapshot)
        speed = number(snapshot.get("backers_per_hour" if kind == "backers" else "goal_progress_pp_per_hour"))
        if speed is None or speed <= 0:
            continue
        result.append({
            "snapshot": snapshot, "project": p, "speed": speed,
            "delta": number(snapshot.get("backer_delta" if kind == "backers" else "goal_completion_delta_pp")),
            "interval": snapshot.get("observation_interval_hours"),
        })
    return sorted(result, key=lambda x: (x["speed"], x["delta"] or 0), reverse=True)


backer_rank = ranking("backers")
goal_rank = ranking("goal")


def growth_rows(rows, kind):
    if not rows:
        return '<tr><td colspan="3" class="empty">目前还没有足够的前后两次数据，下一次更新后再观察。</td></tr>'
    out = []
    for item in rows[:10]:
        p, s = item["project"], item["snapshot"]
        if kind == "backers":
            speed = fmt(item["speed"], 2) + " 人/小时"
            detail = f"本次增加 {signed(item['delta'])} 人 · 现在共 {fmt(p.get('backer_count'))} 人"
        else:
            speed = fmt(item["speed"], 2) + " 个百分点/小时"
            detail = f"本次提升 {signed(item['delta'], 2)} 个百分点 · 现在完成 {fmt(p.get('goal_completion_pct'), 2)}%"
        out.append(f'<tr><td class="project-cell">{link(p.get("project_name"), p.get("project_url"))}{meta(p)}</td><td><strong>{esc(speed)}</strong><small>{esc(detail)}</small></td><td>{esc(fmt(item["interval"], 2))} 小时</td></tr>')
    return "".join(out)


def status_text(value):
    return {"active": "进行中", "completed": "已结束", "ended": "已结束", "paused": "已暂停", "draft": "草稿"}.get(str(value or "").lower(), value or "未知")


def popular_rows():
    rows = sorted(projects, key=lambda r: number(r.get("backer_count")) or 0, reverse=True)[:10]
    if not rows:
        return '<tr><td colspan="5" class="empty">目前没有可展示的项目。</td></tr>'
    out = []
    for i, r in enumerate(rows, 1):
        completion = number(r.get("goal_completion_pct"))
        completion_text = f"{completion:.2f}%" if completion is not None else "—"
        out.append(f'<tr><td class="rank">{i:02d}</td><td class="project-cell">{link(r.get("project_name"), r.get("project_url"))}{meta(r, True)}</td><td><strong>{esc(fmt(r.get("backer_count")))}</strong></td><td>{esc(completion_text)}</td><td><span class="status">{esc(status_text(r.get("status")))}</span></td></tr>')
    return "".join(out)


def funding_rows():
    groups = defaultdict(list)
    for row in projects:
        if number(row.get("raised_amount")) is not None:
            groups[str(row.get("currency") or "未知币种")].append(row)
    if not groups:
        return '<tr><td colspan="5" class="empty">目前没有可比较的筹款金额。</td></tr>'
    chosen = []
    for currency, rows in sorted(groups.items()):
        chosen.extend((currency, r) for r in sorted(rows, key=lambda x: number(x.get("raised_amount")) or 0, reverse=True)[:4])
    out = []
    for currency, row in chosen[:12]:
        pct = number(row.get("goal_completion_pct"))
        pct_text = f"{pct:.2f}%" if pct is not None else "—"
        out.append(f'<tr><td class="project-cell">{link(row.get("project_name"), row.get("project_url"))}{meta(row, True)}</td><td>{esc(currency)}</td><td><strong>{esc(fmt(row.get("raised_amount")))}</strong></td><td>{esc(fmt(row.get("backer_count")))}</td><td>{esc(pct_text)}</td></tr>')
    return "".join(out)


def discovery_cards():
    if not new_rows:
        return '<div class="empty-card"><strong>这次没有首次发现的项目</strong><p>“首次发现”表示系统第一次采集到，不等于项目刚刚上线。</p></div>'
    out = []
    for row in new_rows[:8]:
        p = project_for(row)
        out.append(f'<article class="discovery">{link(p.get("project_name"), p.get("project_url"))}{meta(p, True)}<small>发现时间：{esc(local_time(row.get("checked_at")))}</small></article>')
    return "".join(out)


def event_label(value):
    return {"backers_changed": "支持者人数变化", "funds_changed": "已筹金额变化", "status_changed": "项目状态变化", "new_project": "首次发现项目", "project_discovered": "首次发现项目"}.get(value, value or "项目变化")


def event_rows():
    if not latest_events:
        return '<tr><td colspan="4" class="empty">这次更新没有发现可见变化。</td></tr>'
    out = []
    for row in latest_events[:12]:
        p = by_id.get(row.get("project_id"), {})
        kind = event_label(row.get("event_type"))
        if row.get("event_type") == "funds_changed" and p.get("currency"):
            kind += f"（{p['currency']}）"
        out.append(f'<tr><td class="project-cell">{link(row.get("project_name"), p.get("project_url"))}{meta(p)}</td><td>{esc(kind)}</td><td>{esc(fmt(row.get("old_value"), 2))} → {esc(fmt(row.get("new_value"), 2))}</td><td><strong>{esc(signed(row.get("delta_value"), 2))}</strong></td></tr>')
    return "".join(out)



def sector_stats():
    stats = defaultdict(lambda: {"count": 0, "backers": 0, "amounts": defaultdict(float), "keywords": Counter()})
    all_keywords = Counter()
    for row in projects:
        sector, tags = classes.get(row.get("project_id"), classify(row))
        item = stats[sector]
        item["count"] += 1
        item["backers"] += int(number(row.get("backer_count")) or 0)
        item["amounts"][str(row.get("currency") or "未知币种")] += number(row.get("raised_amount")) or 0
        for tag in tags:
            item["keywords"][tag] += 1
            all_keywords[tag] += 1
    rows = [{"sector": k, **v} for k, v in stats.items()]
    rows.sort(key=lambda x: (x["count"], x["backers"]), reverse=True)
    return rows, all_keywords


sectors, keywords = sector_stats()


def money_text(amounts):
    parts = [f"{c} {v:,.0f}" for c, v in sorted(amounts.items()) if v]
    return " · ".join(parts) if parts else "暂无筹款数据"


def sector_cards():
    if not sectors:
        return '<div class="empty-card"><strong>暂时没有足够数据进行项目方向分析</strong><p>后续采集到项目简介后会自动归类。</p></div>'
    out = []
    for i, item in enumerate(sectors[:6], 1):
        tags = "、".join(item["keywords"].keys()) or "待识别"
        out.append(f'<article class="sector-card"><div class="sector-rank">{i:02d}</div><div class="sector-name">{esc(item["sector"])}</div><div class="sector-number">{item["count"]} <small>个项目</small></div><div class="sector-detail">{item["backers"]:,} 位支持者 · {esc(money_text(item["amounts"]))}</div><div class="sector-keywords">关键词：{esc(tags)}</div></article>')
    return "".join(out)


def keyword_chips():
    return "".join(f'<span class="keyword-chip">{esc(k)} <b>{v}</b></span>' for k, v in keywords.most_common(10))


def sector_insight():
    meaningful = [x for x in sectors if x["sector"] != "其他创意项目"]
    if not meaningful:
        return "当前样本还不足以形成方向判断。"
    by_count = max(meaningful, key=lambda x: (x["count"], x["backers"]))
    by_backers = max(meaningful, key=lambda x: x["backers"])
    return f'在已经识别出的项目方向中，项目数量最多的是<strong>{esc(by_count["sector"])}</strong>（{by_count["count"]}个）；累计支持者最多的是<strong>{esc(by_backers["sector"])}</strong>（{by_backers["backers"]:,}人）。筹款金额按币种分别统计，不把不同币种直接相加。'


def trend_chart():
    grouped = defaultdict(lambda: defaultdict(int))
    for row in snapshots:
        checked = str(row.get("checked_at") or "")
        if not checked:
            continue
        p = project_for(row)
        sector = classes.get(row.get("project_id"), classify(p))[0]
        grouped[checked][sector] += 1
    times = sorted(grouped)[-12:]
    if len(times) < 2:
        return '<div class="empty-card"><strong>趋势线将在积累至少两次采集后显示</strong><p>当前历史快照不足，系统会继续记录。</p></div>'
    top = [x["sector"] for x in sectors if x["sector"] != "其他创意项目"][:5]
    colors = ["#1268a8", "#28a6bd", "#13836f", "#e58a2b", "#8c63b8"]
    width, height, left, right, top_y, bottom = 920, 300, 58, 22, 28, 70
    plot_w, plot_h = width - left - right, height - top_y - bottom
    max_value = max(max(grouped[t].values() or [0]) for t in times) or 1
    x = lambda i: left + plot_w * i / max(len(times) - 1, 1)
    y = lambda v: top_y + plot_h - plot_h * v / max_value
    svg = [f'<svg class="trend-svg" viewBox="0 0 {width} {height}" role="img" aria-label="项目方向数量变化趋势">']
    for tick in range(0, max_value + 1, max(1, (max_value + 3) // 4)):
        yy = y(tick)
        svg.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" class="grid-line"/><text x="{left-12}" y="{yy+4:.1f}" text-anchor="end" class="axis-label">{tick}</text>')
    for i, t in enumerate(times):
        xx = x(i)
        if len(times) <= 8 or i % 2 == 0 or i == len(times) - 1:
            svg.append(f'<text x="{xx:.1f}" y="{height-38}" text-anchor="middle" class="axis-label">{esc(local_time(t, True))}</text>')
    for i, sector in enumerate(top):
        points = " ".join(f'{x(j):.1f},{y(grouped[t].get(sector, 0)):.1f}' for j, t in enumerate(times))
        color = colors[i % len(colors)]
        svg.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for j, t in enumerate(times):
            svg.append(f'<circle cx="{x(j):.1f}" cy="{y(grouped[t].get(sector, 0)):.1f}" r="3.5" fill="{color}"/>')
    svg.append('</svg>')
    legend = "".join(f'<span><i style="background:{colors[i % len(colors)]}"></i>{esc(s)}</span>' for i, s in enumerate(top))
    return "".join(svg) + f'<div class="legend">{legend}</div>'


html_doc = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AI众筹创新雷达｜市场情报看板</title>
<style>
:root{{--ink:#17324d;--muted:#6d8093;--blue:#1268a8;--cyan:#28a6bd;--line:#dce8f1;--paper:#f4f8fb;--white:#fff;--green:#13836f;--soft:#eaf4fa}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",Arial,sans-serif;font-size:15px;line-height:1.55}}.topbar{{background:linear-gradient(115deg,#123553,#176e9b 70%,#2b9aac);color:white;padding:28px max(24px,calc((100vw - 1180px)/2)) 25px;box-shadow:0 8px 24px #163d5718}}.topline{{max-width:1180px;margin:auto;display:flex;justify-content:space-between;gap:20px;align-items:flex-start}}h1{{font-size:32px;letter-spacing:.02em;margin:0 0 5px}}.subtitle{{font-size:16px;margin:0;color:#e8f6fb}}.badge{{border:1px solid #ffffff55;background:#ffffff18;border-radius:99px;padding:7px 13px;font-size:13px;white-space:nowrap}}
main{{max-width:1180px;margin:0 auto;padding:20px 24px 45px}}.meta{{display:flex;flex-wrap:wrap;gap:10px 22px;color:var(--muted);font-size:13px;margin:0 0 12px}}.meta b{{color:var(--ink)}}.notice{{background:#fff6d9;border:1px solid #efd47a;color:#715b16;border-radius:10px;padding:11px 14px;margin-bottom:18px;font-size:14px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}}.metric,.panel{{background:var(--white);border:1px solid var(--line);border-radius:14px;box-shadow:0 5px 18px #31566b0b}}.metric{{padding:17px 18px}}.metric .label{{font-size:13px;color:var(--muted)}}.metric .value{{font-size:29px;font-weight:800;color:var(--blue);margin:3px 0 1px}}.metric .hint{{font-size:12px;color:var(--muted)}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}.panel{{padding:19px 20px;margin-bottom:16px;overflow:hidden}}.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px}}h2{{font-size:20px;margin:0 0 3px;color:#173c5a}}.panel-desc{{color:var(--muted);font-size:13px;margin:0}}.tag{{font-size:12px;color:var(--blue);background:var(--soft);border-radius:99px;padding:4px 9px;white-space:nowrap}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:560px}}th,td{{padding:10px 8px;border-bottom:1px solid #edf2f5;text-align:left;vertical-align:top;font-size:13px}}th{{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}}tr:last-child td{{border-bottom:0}}a{{color:#1268a8;text-decoration:none;font-weight:700}}a:hover{{text-decoration:underline}}.link-mark{{font-size:12px;margin-left:4px;color:var(--cyan)}}.project-cell{{min-width:190px}}.project-cell small{{display:block;margin-top:3px}}.project-meta{{color:var(--muted);font-size:11px;line-height:1.45}}.chip,.keyword-chip{{display:inline-block;background:#eef6fa;color:#236786;border-radius:4px;padding:1px 5px;font-size:11px}}.status{{color:#267260;background:#eaf7f2;padding:3px 7px;border-radius:99px;font-size:12px}}small{{color:var(--muted);font-size:12px;display:block}}.rank{{font-weight:800;color:var(--blue)}}.empty{{color:var(--muted);text-align:center;padding:24px 10px!important}}
.discovery-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.discovery{{background:#f7fbfd;border:1px solid var(--line);border-radius:10px;padding:12px;min-height:100px}}.discovery a{{display:block;margin-bottom:4px}}.empty-card{{display:flex;gap:12px;align-items:flex-start;background:#f7fbfd;border:1px dashed #c6dbe7;border-radius:10px;padding:15px;color:var(--muted)}}.empty-card strong{{color:var(--ink)}}.empty-card p{{margin:3px 0 0;font-size:13px}}.sector-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin-top:5px}}.sector-card{{position:relative;border:1px solid var(--line);border-radius:11px;padding:14px;background:linear-gradient(145deg,#fff,#f4fafc);min-height:144px}}.sector-rank{{position:absolute;right:12px;top:10px;color:#a7bfce;font-weight:800;font-size:18px}}.sector-name{{font-weight:800;color:#174b6a;padding-right:32px}}.sector-number{{font-size:26px;color:var(--blue);font-weight:800;margin-top:8px}}.sector-number small{{display:inline;color:var(--muted);font-size:12px;font-weight:400}}.sector-detail{{font-size:12px;color:#4c6a7b;margin-top:3px}}.sector-keywords{{font-size:12px;color:var(--muted);margin-top:8px;border-top:1px solid #e8f0f4;padding-top:7px}}.insight{{background:#edf7fa;border-left:4px solid var(--cyan);padding:11px 13px;margin:16px 0 13px;color:#36596d;font-size:14px}}.insight strong{{color:#1268a8}}.keyword-line{{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin:5px 0 13px}}.keyword-title{{font-size:13px;color:var(--muted);margin-right:2px}}.keyword-chip b{{margin-left:3px;color:var(--blue)}}.trend-box{{border-top:1px solid var(--line);padding-top:14px}}.trend-title{{font-size:14px;font-weight:800;margin-bottom:4px}}.trend-note{{font-size:12px;color:var(--muted);margin-bottom:8px}}.trend-svg{{width:100%;height:auto;display:block;overflow:visible}}.grid-line{{stroke:#e2edf2;stroke-width:1}}.axis-label{{fill:#8296a5;font-size:11px}}.legend{{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;color:#607888;font-size:12px;margin-top:-3px}}.legend span{{display:inline-flex;align-items:center;gap:5px}}.legend i{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.method{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.method-card{{background:#f7fbfd;border:1px solid var(--line);border-radius:10px;padding:12px}}.method-card strong{{display:block;font-size:14px;margin-bottom:5px;color:#1c5878}}.method-card code{{font-family:inherit;color:var(--muted);font-size:12px;line-height:1.6}}.footer{{text-align:center;color:#8194a1;font-size:12px;padding:8px 0 5px}}@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.sector-grid{{grid-template-columns:repeat(2,1fr)}}.method{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:680px){{.topline{{display:block}}.badge{{display:inline-block;margin-top:12px}}h1{{font-size:27px}}main{{padding:16px 14px 30px}}.grid2{{grid-template-columns:1fr}}.discovery-grid{{grid-template-columns:repeat(2,1fr)}}.sector-grid{{grid-template-columns:1fr 1fr}}.panel{{padding:15px 13px}}}}@media(max-width:440px){{.cards{{grid-template-columns:1fr 1fr;gap:9px}}.metric{{padding:13px}}.metric .value{{font-size:24px}}.method{{grid-template-columns:1fr}}.sector-grid{{grid-template-columns:1fr}}}}@media print{{body{{background:white}}.topbar{{background:#175b83!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}.panel,.metric{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>
<header class="topbar"><div class="topline"><div><h1>AI众筹创新雷达</h1><p class="subtitle">自动发现众筹项目，比较项目表现，观察创新方向变化</p></div><span class="badge">模块一 · Indiegogo 监测看板</span></div></header><main>
<div class="meta"><span>最近成功更新：<b>{esc(local_time(latest))}</b></span><span>两次采集间隔：<b>{esc(interval_label)}</b></span><span>数据来源：<b>Indiegogo公开项目</b></span></div><div class="notice">系统计划每2小时自动采集一次。页面显示最近一次成功采集的结果；GitHub Actions的实际启动时间可能出现少量延迟。</div>
<section class="cards"><div class="metric"><div class="label">当前跟踪项目</div><div class="value">{len(projects):,}</div><div class="hint">系统目前持续记录的项目数</div></div><div class="metric"><div class="label">本次首次发现</div><div class="value">{len(new_rows):,}</div><div class="hint">本次第一次采集到的项目数</div></div><div class="metric"><div class="label">本次发生变化</div><div class="value">{len(set(r.get("project_id") for r in latest_events)):,}</div><div class="hint">支持者、筹款或状态发生变化</div></div><div class="metric"><div class="label">两次采集间隔</div><div class="value">{esc(interval_label)}</div><div class="hint">本次与上次采集之间的时间</div></div></section>
<div class="grid2"><section class="panel"><div class="panel-head"><div><h2>支持者增长最快</h2><p class="panel-desc">按每小时新增支持者人数排序，观察项目升温速度</p></div><span class="tag">每小时新增人数</span></div><div class="table-wrap"><table><thead><tr><th>项目</th><th>增长速度</th><th>采集间隔</th></tr></thead><tbody>{growth_rows(backer_rank, "backers")}</tbody></table></div></section><section class="panel"><div class="panel-head"><div><h2>目标完成率提升最快</h2><p class="panel-desc">按每小时提升的目标完成率排序</p></div><span class="tag">每小时提升百分点</span></div><div class="table-wrap"><table><thead><tr><th>项目</th><th>提升速度</th><th>采集间隔</th></tr></thead><tbody>{growth_rows(goal_rank, "goal")}</tbody></table></div></section></div>
<section class="panel"><div class="panel-head"><div><h2>本次首次发现</h2><p class="panel-desc">本次第一次采集到的项目；首次发现不等于项目刚刚上线</p></div><span class="tag">{len(new_rows)} 个项目</span></div><div class="discovery-grid">{discovery_cards()}</div></section>
<section class="panel"><div class="panel-head"><div><h2>项目方向：现在大家在做什么</h2><p class="panel-desc">根据项目名称和简介自动归类，帮助快速观察前沿创意集中在哪些方向</p></div><span class="tag">自动归类 · 教学分析</span></div><div class="insight">{sector_insight()}</div><div class="keyword-line"><span class="keyword-title">常见关键词（涉及项目数）：</span>{keyword_chips()}</div><div class="sector-grid">{sector_cards()}</div><div class="trend-box"><div class="trend-title">项目方向数量变化</div><div class="trend-note">每个时间点统计当时被系统跟踪的项目数量；用于观察方向热度变化，不代表行业规模。</div>{trend_chart()}</div></section>
<div class="grid2"><section class="panel"><div class="panel-head"><div><h2>支持者人数最多</h2><p class="panel-desc">按当前累计支持者人数排序，反映项目当前参与规模</p></div><span class="tag">前10名</span></div><div class="table-wrap"><table><thead><tr><th>#</th><th>项目 / 方向</th><th>支持者</th><th>目标完成率</th><th>状态</th></tr></thead><tbody>{popular_rows()}</tbody></table></div></section><section class="panel"><div class="panel-head"><div><h2>各币种筹款较高项目</h2><p class="panel-desc">每种币种分别排列，避免把不同币种直接相加</p></div><span class="tag">当前数据</span></div><div class="table-wrap"><table><thead><tr><th>项目 / 方向</th><th>币种</th><th>已筹金额</th><th>支持者</th><th>目标完成率</th></tr></thead><tbody>{funding_rows()}</tbody></table></div></section></div>
<section class="panel"><div class="panel-head"><div><h2>最近一次项目变化</h2><p class="panel-desc">显示项目与上次采集相比发生了什么变化</p></div><span class="tag">{len(latest_events)} 条变化</span></div><div class="table-wrap"><table><thead><tr><th>项目 / 方向</th><th>变化内容</th><th>上次 → 本次</th><th>变化量</th></tr></thead><tbody>{event_rows()}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><h2>指标说明</h2><p class="panel-desc">看板中的数字怎么算、应该怎样理解</p></div></div><div class="method"><div class="method-card"><strong>支持者增长速度</strong><code>本次新增支持者人数 ÷ 两次采集间隔（小时）</code></div><div class="method-card"><strong>目标完成率提升速度</strong><code>目标完成率变化百分点 ÷ 两次采集间隔（小时）</code></div><div class="method-card"><strong>项目方向与关键词</strong><code>根据项目名称和简介自动归类，用于观察趋势，不等同于官方行业标签</code></div><div class="method-card"><strong>如何使用这些数字</strong><code>短期变化是观察信号；项目热度不等于产品质量、市场成功或投资建议</code></div></div></section>
<div class="footer">数据来自公开项目信息 · 系统按计划自动采集并更新页面 · 项目方向仅用于观察和教学分析</div></main></body></html>'''

OUT.write_text(html_doc, encoding="utf-8")
print(f"看板已生成：{OUT}")
print(f"项目数：{len(projects)}；本次首次发现：{len(new_rows)}；发生变化：{len(set(r.get('project_id') for r in latest_events))}；间隔：{interval_label}")
