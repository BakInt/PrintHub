# -*- coding: utf-8 -*-
"""第三轮修补：把「移动手机端 · 亮色」palette 补成完整独立的一套。

背景：移动亮色块原本只覆盖了品牌/中性/边框/文字，其余（状态色、阴影、
--cp-img-filter、--cp-swatch-inset、--cp-overlay、--cp-preview-bg）都靠
`:root` 继承。这违反「PC 与移动端两套独立配色」的要求——改了 PC 亮色会
连带改到手机端亮色。这里把缺口补齐，让四个 palette 的定义集合完全一致。

「移动手机端 · 深色」只缺 4 个（其余已单独适配），一并补齐。
取值：亮色状态色沿用原 PC 亮色的取值（语义色不随设备改），其余为手机端
蓝紫风的对应值。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, 'frontend', 'src', 'assets', 'theme.css')

MOBILE_LIGHT_ANCHOR = '''    --cp-shadow-tabbar: 0 -6px 20px rgba(15, 23, 42, 0.12);
    --cp-white-soft: rgba(255, 255, 255, 0.16);
    --cp-white-dim: rgba(255, 255, 255, 0.88);'''

MOBILE_LIGHT_ADD = '''
    /* 状态色（移动亮色单独成组，不继承 PC 端） */
    --cp-success: #16a34a;
    --cp-success-strong: #15803d;
    --cp-success-badge: #166534;
    --cp-success-soft: #f0fdf4;
    --cp-success-border: #bbf7d0;
    --cp-success-chip: #dcfce7;
    --cp-warn: #92400e;
    --cp-warn-soft: #fef3c7;
    --cp-danger: #dc2626;
    --cp-danger-strong: #b91c1c;
    --cp-danger-deep: #991b1b;
    --cp-danger-soft: #fef2f2;
    --cp-danger-softest: #fff7f7;
    --cp-danger-border: #fecaca;
    --cp-danger-chip: #fee2e2;

    /* 品牌补全 / 媒体（移动亮色同样显式声明，避免继承 PC 端） */
    --cp-brand-strong: #3730a3;
    --cp-img-filter: none;
    --cp-preview-bg: #fff;
    --cp-swatch-inset: inset 0 0 0 1px rgba(15, 23, 42, 0.12);
    --cp-shadow-1: 0 1px 2px rgba(15, 23, 42, 0.04);
    --cp-shadow-3: 0 6px 18px rgba(15, 23, 42, 0.05);
    --cp-shadow-4: 0 8px 24px rgba(15, 23, 42, 0.08);
    --cp-shadow-5: 0 14px 34px rgba(15, 23, 42, 0.05);
    --cp-shadow-6: 0 14px 34px rgba(15, 23, 42, 0.16);
    --cp-shadow-brand: 0 8px 20px rgba(79, 70, 229, 0.24);
    --cp-overlay: rgba(15, 23, 42, 0.5);'''

MOBILE_DARK_ANCHOR = '''    --cp-shadow-tabbar: 0 -6px 20px rgba(0, 0, 0, 0.6);
    --cp-white-soft: rgba(255, 255, 255, 0.18);
    --cp-white-dim: rgba(255, 255, 255, 0.92);'''

MOBILE_DARK_ADD = '''
    --cp-brand-strong: #a5b4fc;
    --cp-img-filter: brightness(0.92) contrast(1.04);
    --cp-shadow-brand: 0 8px 20px rgba(79, 70, 229, 0.4);
    --cp-swatch-inset: inset 0 0 0 1px rgba(255, 255, 255, 0.2);'''


def build_manual_light():
    """重建移动亮色块（原块内容 + 追加完整定义），顺序稳定。"""
    return MOBILE_LIGHT_ANCHOR + MOBILE_LIGHT_ADD


def main():
    text = io.open(THEME, encoding='utf-8', newline='').read()
    changed = 0

    if '--cp-brand-strong: #3730a3;' in text:
        print('移动亮色已补齐，跳过')
    elif MOBILE_LIGHT_ANCHOR in text:
        text = text.replace(MOBILE_LIGHT_ANCHOR, build_manual_light(), 1)
        changed += 1
    else:
        raise SystemExit('未找到移动亮色锚点')

    if '--cp-brand-strong: #a5b4fc;' in text:
        print('移动深色已补齐，跳过')
    elif MOBILE_DARK_ANCHOR in text:
        text = text.replace(MOBILE_DARK_ANCHOR, MOBILE_DARK_ANCHOR + MOBILE_DARK_ADD, 1)
        changed += 1
    else:
        raise SystemExit('未找到移动深色锚点')

    io.open(THEME, 'w', encoding='utf-8', newline='').write(text)
    print('移动端 palette 修补完成，改动块数:', changed)


if __name__ == '__main__':
    main()
