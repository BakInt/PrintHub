"""一次性工具：主题化后自检。
1) 对比 git HEAD 与工作区 styles.css，确认没有丢内容；
2) 校验所有 var(--cp-*) 都在 theme.css 里定义；
3) 报告仍写死的颜色与自定义属性定义清单。
用法：python scripts/theme_check.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "frontend/src/assets/styles.css"
THEME = ROOT / "frontend/src/assets/theme.css"
GIT = r"C:\Program Files\Git\cmd\git.exe"
REL = "frontend/src/assets/styles.css"


def git_bytes(rev_path):
    return subprocess.run(
        [GIT, "show", rev_path], cwd=str(ROOT), stdout=subprocess.PIPE, check=True
    ).stdout


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def main():
    head = git_bytes(f"HEAD:{REL}").decode("utf-8")
    work = STYLES.read_text(encoding="utf-8")
    theme = THEME.read_text(encoding="utf-8")
    work_code = strip_comments(work)

    print("== 行数/字符数 ==")
    print("HEAD:", head.count("\n") + 1, "lines", len(head), "chars")
    print("work:", work.count("\n") + 1, "lines", len(work), "chars")

    head_selectors = set(re.findall(r"\.[a-zA-Z][\w-]*", head))
    work_selectors = set(re.findall(r"\.[a-zA-Z][\w-]*", work))
    print("== 选择器（.class）差异 ==")
    print("HEAD 有、work 缺失:", sorted(head_selectors - work_selectors)[:40])
    print("work 新增:", sorted(work_selectors - head_selectors)[:40])
    print("选择器个数 HEAD/work:", len(head_selectors), len(work_selectors))

    print("== 声明差异（按 属性: 值 归一后计数）==")
    head_decls = re.findall(r"([a-z-]+):\s*([^;{}]+)", head)
    work_decls = re.findall(r"([a-z-]+):\s*([^;{}]+)", work)
    print("声明数 HEAD/work:", len(head_decls), len(work_decls))

    defined = set(re.findall(r"(--cp-[\w-]+):", theme))
    used = set(re.findall(r"var\((--cp-[\w-]+)", work_code))
    print("== 变量 ==")
    print("定义:", len(defined), "使用:", len(used))
    print("使用但未定义:", sorted(used - defined))
    print("定义但未使用:", sorted(defined - used))

    leftovers = sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", work)))
    others = sorted(set(re.findall(r"\brgba?\([^)]*\)", work)))
    print("== 仍写死的颜色 ==")
    print("hex:", leftovers)
    print("rgb/rgba:", others[:40], "共", len(others))

    print("== 花括号平衡 ==")
    print("work {", work.count("{"), "}", work.count("}"))
    print("theme {", theme.count("{"), "}", theme.count("}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
