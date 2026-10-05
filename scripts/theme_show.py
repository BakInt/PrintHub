"""按行号打印 styles.css 指定行（原样，含中文），供人工核对。"""
import sys
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "frontend/src/assets/styles.css"
lines = path.read_text(encoding="utf-8").splitlines()

wanted = []
for arg in sys.argv[1:]:
    if "-" in arg:
        a, b = arg.split("-")
        wanted.extend(range(int(a), int(b) + 1))
    else:
        wanted.append(int(arg))

out = []
for number in sorted(set(wanted)):
    if 1 <= number <= len(lines):
        out.append(f"{number:4d}| {lines[number - 1]}")
sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
