from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "radar" / "AI众筹创新雷达_本地看板.html"
DESTINATION = ROOT / "site" / "index.html"


def main() -> None:
    source = SOURCE if SOURCE.is_file() else DESTINATION
    if not source.is_file():
        raise FileNotFoundError(f"看板生成文件不存在：{SOURCE}")
    document = source.read_text(encoding="utf-8")
    lower = document.lower()
    if "</head>" not in lower:
        raise RuntimeError("看板HTML缺少</head>，无法安全加入自动刷新设置。")
    refresh = '<meta http-equiv="refresh" content="300">\n'
    if 'http-equiv="refresh"' not in lower and "http-equiv='refresh'" not in lower:
        head_end = lower.index("</head>")
        document = document[:head_end] + refresh + document[head_end:]
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(document, encoding="utf-8")
    if DESTINATION.stat().st_size < 1000:
        raise RuntimeError("发布文件异常过小，停止发布。")
    print(f"已准备公开看板：{DESTINATION}")
    print("页面每5分钟自动刷新；项目数据按每2小时采集一次更新。")


if __name__ == "__main__":
    main()
