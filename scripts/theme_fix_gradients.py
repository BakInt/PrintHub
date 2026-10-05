"""一次性修补：恢复被合并掉的渐变端点（两个 hex 曾映射到同一个 token）。"""
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "frontend/src/assets/styles.css"
text = path.read_text(encoding="utf-8")

fixes = [
    # 上传区渐变（原 #f8fbff → #eef5ff）
    ("linear-gradient(180deg, var(--cp-gradient-drop), var(--cp-gradient-drop))",
     "linear-gradient(180deg, var(--cp-gradient-drop), var(--cp-gradient-drop-2))"),
    # 手机端顶部栏渐变（原 #eef2ff → #f5f3ff）
    ("linear-gradient(135deg, var(--cp-brand-soft) 0%, var(--cp-gradient-soft) 100%)",
     "linear-gradient(135deg, var(--cp-brand-soft) 0%, var(--cp-gradient-soft) 55%, var(--cp-brand-mid) 100%)"),
    # 手机端上传区主渐变（原 #4f46e5 0% → #6366f1 55% → #818cf8 100%）
    ("linear-gradient(150deg, var(--cp-brand) 0%, var(--cp-brand-bright) 55%, var(--cp-brand-bright) 100%)",
     "linear-gradient(150deg, var(--cp-brand) 0%, var(--cp-brand-bright) 55%, var(--cp-brand-hi) 100%)"),
]

for old, new in fixes:
    if old not in text:
        raise SystemExit("未找到待修补片段: %s" % old[:60])
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8", newline="")
print("gradient fixes applied:", len(fixes))
