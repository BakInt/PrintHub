# -*- coding: utf-8 -*-
"""修复第二轮主题化的两个缺陷（一次性工具，可复跑）：

1. theme.css 四个 palette 缺少三个阴影 token
   （--cp-shadow-brand-lg / --cp-shadow-button / --cp-shadow-tabbar），
   以及手机端专用白覆盖 token（--cp-white-soft / --cp-white-dim），
   导致对应的 box-shadow / background / color 计算为空。
2. styles.css 手机端三处颜色丢掉了 var() 包裹，写成了裸的 --cp-*。

取值来源：scripts/theme_tokenize.py 的映射表（原始写死值）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, 'frontend', 'src', 'assets', 'theme.css')
STYLES = os.path.join(ROOT, 'frontend', 'src', 'assets', 'styles.css')

# 按文件顺序出现的 palette 锚点 -> 追加行（追加在锚点行之后）
THEME_ANCHORS = [
    # 1. PC 亮色
    ('  --cp-shadow-brand: 0 8px 20px rgba(37, 99, 235, 0.18);',
     ['  --cp-shadow-brand-lg: 0 16px 34px rgba(79, 70, 229, 0.32);',
      '  --cp-shadow-button: 0 8px 18px rgba(37, 99, 235, 0.22);',
      '  --cp-shadow-tabbar: 0 -6px 20px rgba(15, 23, 42, 0.08);',
      '  --cp-white-soft: rgba(255, 255, 255, 0.16);',
      '  --cp-white-dim: rgba(255, 255, 255, 0.86);']),
    # 2. PC 深色
    ('  --cp-shadow-brand: 0 8px 20px rgba(37, 99, 235, 0.35);',
     ['  --cp-shadow-brand-lg: 0 16px 34px rgba(37, 99, 235, 0.4);',
      '  --cp-shadow-button: 0 8px 18px rgba(37, 99, 235, 0.32);',
      '  --cp-shadow-tabbar: 0 -6px 20px rgba(0, 0, 0, 0.55);',
      '  --cp-white-soft: rgba(255, 255, 255, 0.14);',
      '  --cp-white-dim: rgba(255, 255, 255, 0.9);']),
    # 3. 移动亮色（原文件该块没有阴影声明，补一套蓝紫风的）
    ('    --cp-ink-muted: #94a3b8;',
     ['    --cp-shadow-brand-lg: 0 16px 34px rgba(79, 70, 229, 0.32);',
      '    --cp-shadow-button: 0 8px 18px rgba(79, 70, 229, 0.28);',
      '    --cp-shadow-tabbar: 0 -6px 20px rgba(15, 23, 42, 0.12);',
      '    --cp-white-soft: rgba(255, 255, 255, 0.16);',
      '    --cp-white-dim: rgba(255, 255, 255, 0.88);']),
    # 4. 移动深色
    ('    --cp-ink-muted: #828cb0;',
     ['    --cp-shadow-brand-lg: 0 16px 34px rgba(79, 70, 229, 0.38);',
      '    --cp-shadow-button: 0 8px 18px rgba(79, 70, 229, 0.36);',
      '    --cp-shadow-tabbar: 0 -6px 20px rgba(0, 0, 0, 0.6);',
      '    --cp-white-soft: rgba(255, 255, 255, 0.18);',
      '    --cp-white-dim: rgba(255, 255, 255, 0.92);']),
]

STYLES_FIXES = [
    ('color: --cp-white-dim;', 'color: var(--cp-white-dim);'),
    ('background: --cp-white-soft;', 'background: var(--cp-white-soft);'),
]


def patch_theme():
    text = io.open(THEME, encoding='utf-8', newline='').read()
    cursor = 0
    for anchor, adds in THEME_ANCHORS:
        pos = text.find(anchor, cursor)
        if pos < 0:
            print('anchor not found (already patched?): %r' % anchor)
            continue
        end = pos + len(anchor)
        text = text[:end] + '\n' + '\n'.join(adds) + text[end:]
        cursor = end + len(adds) + 1
    io.open(THEME, 'w', encoding='utf-8', newline='').write(text)
    print('patched', os.path.relpath(THEME, ROOT))


def patch_styles():
    text = io.open(STYLES, encoding='utf-8', newline='').read()
    for old, new in STYLES_FIXES:
        if old not in text:
            print('skip (already patched): %r' % old)
            continue
        text = text.replace(old, new)
    io.open(STYLES, 'w', encoding='utf-8', newline='').write(text)
    print('patched', os.path.relpath(STYLES, ROOT))


def main():
    patch_theme()
    patch_styles()


if __name__ == '__main__':
    main()
