"""审计：Vue 模板/脚本里出现的 class 名是否都在 styles.css 里有样式规则。

只做提示，不修改文件。用于确认主题化过程中没有弄丢任何样式。
用法：python scripts/theme_class_audit.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "frontend/src/assets/styles.css"
VIEWS = sorted((ROOT / "frontend/src").rglob("*.vue"))

css = CSS.read_text(encoding="utf-8")
css_code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", css_code))

used = {}
for view in VIEWS:
    text = view.read_text(encoding="utf-8")
    for match in re.finditer(r'class="([^"]+)"', text):
        for token in match.group(1).split():
            if "{" in token or "$" in token or ":" in token:
                continue
            used.setdefault(token, set()).add(view.name)
    for match in re.finditer(r"'([a-z][\w-]*)'", text):
        token = match.group(1)
        if "-" in token:
            used.setdefault(token, set()).add(view.name)

missing = {name: files for name, files in used.items() if name not in defined}
print("样式规则数:", len(defined), "模板/脚本里用到的 class 数:", len(used))
print("=== 有 class 但样式表里没有规则（可能是动态类或遗漏）===")
for name in sorted(missing):
    print("  %-32s %s" % (name, ", ".join(sorted(missing[name]))))
print("=== 样式表里有但当前模板没用到的 class（只列前 60 个）===")
unused = sorted(defined - set(used))
print(" 共", len(unused))
print("  " + " ".join(unused[:60]))
