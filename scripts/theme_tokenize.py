"""一次性脚本：把 frontend/src/assets/styles.css 里的写死颜色统一换成主题变量。

用法：python fix_colors.py <已从 git 恢复的 styles.css 路径> [输出文件]
说明：按 UTF-8 + 原始换行读写，避免编码/行尾被改动；单个 token 首次出现即替换。
"""
import sys
import re

TOKENS = [
    ("#f8fbff", "--cp-gradient-drop"),
    ("#eef5ff", "--cp-gradient-drop"),
    ("#f8faff", "--cp-gradient-card"),
    ("#f7fbff", "--cp-gradient-card"),
    ("#eef4ff", "--cp-gradient-intro"),
    ("#f5f3ff", "--cp-gradient-soft"),
    ("#ddd6fe", "--cp-chip-accent"),
    ("#0f766e", "--cp-accent-deep"),
    ("#60a5fa", "--cp-brand-bright"),
    ("#3b82f6", "--cp-brand-mid"),
    ("#6366f1", "--cp-brand-bright"),
    ("#818cf8", "--cp-brand-bright"),
    ("#ef4444", "--cp-swatch-red"),
    ("#f59e0b", "--cp-swatch-amber"),
    ("#22c55e", "--cp-swatch-green"),
    ("#06b6d4", "--cp-swatch-cyan"),
    ("#a855f7", "--cp-swatch-purple"),
    ("#2563eb", "--cp-brand"),
    ("#1d4ed8", "--cp-brand-deep"),
    ("#1e40af", "--cp-brand-text"),
    ("#bfdbfe", "--cp-brand-border"),
    ("#eff6ff", "--cp-brand-soft"),
    ("#dbeafe", "--cp-brand-softer"),
    ("#1e3a8a", "--cp-brand-emphasis"),
    ("#4f46e5", "--cp-brand"),
    ("#4338ca", "--cp-brand-text"),
    ("#e0e7ff", "--cp-brand-border"),
    ("#eef2ff", "--cp-brand-soft"),
    ("#c7d2fe", "--cp-border-mid"),
    ("#0f172a", "--cp-ink-title"),
    ("#1e293b", "--cp-ink-strong"),
    ("#1f2937", "--cp-ink-strong"),
    ("#334155", "--cp-ink-body"),
    ("#475569", "--cp-ink-body"),
    ("#64748b", "--cp-ink-sub"),
    ("#94a3b8", "--cp-ink-muted"),
    ("#ffffff", "--cp-surface"),
    ("#fff", "--cp-surface"),
    ("#f8fafc", "--cp-soft"),
    ("#f1f5f9", "--cp-softer"),
    ("#f1f5fb", "--cp-app-bg"),
    ("#e2e8f0", "--cp-border"),
    ("#e6e9f5", "--cp-border-soft"),
    ("#cbd5e1", "--cp-border-mid"),
    ("#d6dced", "--cp-border-input"),
    ("#16a34a", "--cp-success"),
    ("#15803d", "--cp-success-strong"),
    ("#166534", "--cp-success-badge"),
    ("#f0fdf4", "--cp-success-soft"),
    ("#bbf7d0", "--cp-success-border"),
    ("#dcfce7", "--cp-success-chip"),
    ("#dc2626", "--cp-danger"),
    ("#b91c1c", "--cp-danger-strong"),
    ("#991b1b", "--cp-danger-deep"),
    ("#fef2f2", "--cp-danger-soft"),
    ("#fff7f7", "--cp-danger-softest"),
    ("#fecaca", "--cp-danger-border"),
    ("#fee2e2", "--cp-danger-chip"),
    ("#92400e", "--cp-warn"),
    ("#fef3c7", "--cp-warn-soft"),
]

SHADOWS = [
    ("0 8px 20px rgba(37, 99, 235, 0.18)", "--cp-shadow-brand"),
    ("0 14px 34px rgba(15, 23, 42, 0.05)", "--cp-shadow-5"),
    ("0 14px 34px rgba(15, 23, 42, 0.16)", "--cp-shadow-6"),
    ("0 8px 24px rgba(15, 23, 42, 0.08)", "--cp-shadow-4"),
    ("0 6px 18px rgba(15, 23, 42, 0.05)", "--cp-shadow-3"),
    ("0 1px 2px rgba(15, 23, 42, 0.04)", "--cp-shadow-1"),
    ("0 16px 34px rgba(79, 70, 229, 0.32)", "--cp-shadow-brand-lg"),
    ("0 8px 18px rgba(79, 70, 229, 0.22)", "--cp-shadow-button"),
    ("0 8px 18px rgba(79, 70, 229, 0.28)", "--cp-shadow-button"),
    ("0 6px 16px rgba(79, 70, 229, 0.28)", "--cp-shadow-button"),
    ("0 -6px 20px rgba(15, 23, 42, 0.08)", "--cp-shadow-tabbar"),
    ("inset 0 0 0 1px rgba(15, 23, 42, 0.12)", "--cp-swatch-inset"),
    ("rgba(248, 250, 252, 0.97)", "--cp-surface-glass"),
    ("rgba(255, 255, 255, 0.98)", "--cp-surface-glass"),
    ("rgba(15, 23, 42, 0.5)", "--cp-overlay"),
]

GRADIENTS = [
    ("rgba(255, 255, 255, 0.16)", "--cp-white-soft"),
    ("rgba(255, 255, 255, 0.86)", "--cp-white-dim"),
    ("rgba(255, 255, 255, 0.85)", "--cp-white-dim"),
    ("#eef2ff, #f5f3ff", "var(--cp-brand-soft), var(--cp-gradient-soft)"),
    ("#4f46e5 0%, #6366f1 55%, #818cf8 100%",
     "var(--cp-brand) 0%, var(--cp-brand-bright) 55%, var(--cp-brand-hi) 100%"),
    ("#4338ca, #4f46e5 55%, #6366f1",
     "var(--cp-brand-text), var(--cp-brand) 55%, var(--cp-brand-bright)"),
    ("#4f46e5, #6366f1", "var(--cp-brand), var(--cp-brand-bright)"),
    ("#1d4ed8, #2563eb 58%, #0f766e",
     "var(--cp-brand-deep), var(--cp-brand) 58%, var(--cp-accent-deep)"),
    ("#2563eb, #60a5fa", "var(--cp-brand), var(--cp-brand-bright)"),
    ("#eef2ff 0%, #f5f3ff 100%", "var(--cp-brand-soft) 0%, var(--cp-gradient-soft) 100%"),
    ("#f5f3ff, #eef2ff", "var(--cp-gradient-soft), var(--cp-brand-soft)"),
]

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else src

with open(src, "r", encoding="utf-8", newline="") as handle:
    text = handle.read()
original = text

for key, token in TOKENS:
    text = text.replace(key, "var(%s)" % token)

for key, token in SHADOWS:
    text = text.replace(key, "var(%s)" % token)

for key, token in GRADIENTS:
    text = text.replace(key, token)

with open(dst, "w", encoding="utf-8", newline="") as handle:
    handle.write(text)

left = sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}\b", text)))
print("replaced hex tokens:", len(TOKENS), "lines:", text.count("\n") + 1)
print("remaining hex:", left)
print("len before/after:", len(original), len(text))
