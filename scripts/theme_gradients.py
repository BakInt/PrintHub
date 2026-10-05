"""列出 styles.css 里所有渐变，便于人工确认渐变端点是否被合并成同一个 token。"""
import re
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "frontend/src/assets/styles.css"
text = path.read_text(encoding="utf-8")

for index, line in enumerate(text.splitlines(), 1):
    for match in re.finditer(r"[a-z-]*gradient\(([^;]*?)\)(?=[,;\s]|$)", line):
        body = match.group(1)
        tokens = re.findall(r"var\((--cp-[\w-]+)\)", body)
        dup = len(tokens) != len(set(tokens))
        flag = "DUP " if dup else "    "
        print(f"{flag}{index:4d} {match.group(0)[:150]}")
