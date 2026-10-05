"""列出 styles.css 里所有 box-shadow 相关行，确认是否还有写死的阴影色。"""
from pathlib import Path
import sys

path = Path(__file__).resolve().parent.parent / "frontend/src/assets/styles.css"
lines = path.read_text(encoding="utf-8").splitlines()
out = [f"{i:4d}| {line}" for i, line in enumerate(lines, 1)
       if "box-shadow" in line or "shadow" in line or "rgba(" in line]
sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
