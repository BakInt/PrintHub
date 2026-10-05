"""一次性收尾：色卡改用主题色卡变量 + 内描边，并清掉确实用不到的自定义属性。"""
import re
from pathlib import Path

base = Path(__file__).resolve().parent.parent / "frontend/src/assets"
styles = base / "styles.css"
theme = base / "theme.css"

text = styles.read_text(encoding="utf-8")

swatch_fix = [
    (".swatch.color { background: conic-gradient(from 210deg, var(--cp-swatch-red), var(--cp-swatch-amber), var(--cp-swatch-green), var(--cp-swatch-cyan), var(--cp-brand-mid), var(--cp-swatch-purple), var(--cp-swatch-red)); }",
     ".swatch.color { background: conic-gradient(from 210deg, var(--cp-swatch-red), var(--cp-swatch-amber), var(--cp-swatch-green), var(--cp-swatch-cyan), var(--cp-brand-mid), var(--cp-swatch-purple), var(--cp-swatch-red)); box-shadow: var(--cp-swatch-inset); }"),
]
for old, new in swatch_fix:
    if old in text:
        text = text.replace(old, new)
        print("swatch updated")
    else:
        print("swatch pattern not found (skip)")

styles.write_text(text, encoding="utf-8", newline="")

theme_text = theme.read_text(encoding="utf-8")
removed = 0
for token in ["--cp-gradient-card", "--cp-white-soft", "--cp-white-dim"]:
    pattern = re.compile(r"^[ \t]*%s:.*\n" % re.escape(token), re.M)
    theme_text, count = pattern.subn("", theme_text)
    removed += count
# 清掉移除后留下的孤立注释行（只处理明确标注那两类）
theme_text = theme_text.replace("  /* 叠加在彩色渐变上的白色高光（进度条/徽标） */\n", "")
theme.write_text(theme_text, encoding="utf-8", newline="")
print("removed token lines:", removed)
