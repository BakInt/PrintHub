# -*- coding: utf-8 -*-
"""主题一致性审计（只读，一次性工具）：

1. styles.css 里用到的每个 var(--cp-*) 都必须在 theme.css 里定义；
2. 四个 palette 块（PC 亮 / PC 深 / 移动亮 / 移动深）的定义集合必须完全一致
   （少一个变量会在对应设备+主题下取到空值）；
3. 统计每个 palette 的变量数量与块内是否存在重复定义。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, 'frontend', 'src', 'assets', 'theme.css')
STYLES = os.path.join(ROOT, 'frontend', 'src', 'assets', 'styles.css')

VAR_DEF = re.compile(r'(--cp-[a-z0-9-]+)\s*:')
VAR_USE = re.compile(r'var\(\s*(--cp-[a-z0-9-]+)')


def strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def blocks(text):
    """按出现顺序切出四个 palette 块：返回 [(名字, 块文本)]。"""
    out = []
    # 定位四个块的开头
    starts = []
    for m in re.finditer(r':root(\[data-theme=.dark.\])?\s*\{', text):
        # 判断该 :root 是否位于移动端媒体查询内
        prefix = text[:m.start()]
        depth_media = prefix.rfind('@media (max-width: 767px)')
        inner = prefix[depth_media:]
        mobile = depth_media >= 0 and inner.count('{') > inner.count('}')
        dark = 'dark' in m.group(0)
        name = ('移动' if mobile else 'PC') + ('深色' if dark else '亮色')
        starts.append((name, m.start()))
    for i, (name, s) in enumerate(starts):
        e = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        out.append((name, text[s:e]))
    return out


def defs(chunk):
    names = VAR_DEF.findall(chunk)
    return names


def main():
    theme_raw = io.open(THEME, encoding='utf-8', newline='').read()
    styles_raw = io.open(STYLES, encoding='utf-8', newline='').read()
    theme = strip_comments(theme_raw)
    styles = strip_comments(styles_raw)

    palettes = blocks(theme)
    if len(palettes) != 4:
        print('!! 期望 4 个 palette，实际 %d 个' % len(palettes))
    sets = {}
    for name, chunk in palettes:
        names = defs(chunk)
        dup = sorted({n for n in names if names.count(n) > 1})
        sets[name] = set(names)
        print('%-6s 定义 %d 个变量%s' % (name, len(set(names)),
              ('，重复: ' + ', '.join(dup)) if dup else ''))

    used = set(VAR_USE.findall(styles))
    all_defined = set()
    for s in sets.values():
        all_defined |= s
    print()
    print('styles.css 使用 %d 个变量' % len(used))
    missing = sorted(used - all_defined)
    print('使用但未定义:', missing if missing else '无')
    unused = sorted(all_defined - used)
    print('定义但未使用:', unused if unused else '无')

    print()
    if len(sets) >= 2:
        names = list(sets)
        base = sets[names[0]]
        for n in names[1:]:
            only_base = sorted(base - sets[n])
            only_other = sorted(sets[n] - base)
            if only_base or only_other:
                print('!! %s 与 %s 不一致' % (names[0], n))
                print('   仅 %s 有: %s' % (names[0], only_base))
                print('   仅 %s 有: %s' % (n, only_other))
        else:
            pass
        if all(sets[n] == base for n in names[1:]):
            print('四个 palette 定义集合完全一致（%d 个变量）' % len(base))

    # 裸变量检测
    bare = [l.strip() for l in styles.split('\n')
            if re.search(r'(?<![\w-])--cp-[a-z0-9-]+', l)
            and not re.search(r'var\(\s*--cp-', l)
            and '--cp' in l and ':' in l]
    real_bare = []
    for i, l in enumerate(styles.split('\n'), 1):
        for m in re.finditer(r'(?<![\w-])--cp-[a-z0-9-]+', l):
            s = m.start()
            if not l[max(0, s - 4):s].endswith('var('):
                real_bare.append((i, l.strip()))
    print()
    print('裸变量引用（缺少 var()）:', real_bare if real_bare else '无')


if __name__ == '__main__':
    main()
