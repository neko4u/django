# apps/helpdocs/toc.py
"""帮助中心：给正文标题注入锚点 id + 抽取左侧目录。

约定：
  - 只收录 h2 / h3 / h4（h1 留给文档标题，h5/h6 太细碎）
  - 作者手写的 id 一律保留；重名或缺失才自动补 sec-1 / sec-2 …
  - 标题带 class="no-toc" 时：仍然补 id（方便直接链接），但不进目录

为什么用正则而不是 bs4：
  项目没有 beautifulsoup4 依赖，而且 bs4 会重排 / 补齐 HTML；
  正文在保存时已经过 bleach（html5lib）规整过，标签是闭合的，
  正则在「只改开标签」这件事上更可控。
"""

import html as html_mod
import re

# h2/h3/h4 的完整标签（开标签 + 内容 + 对应闭标签）
_HEADING_RE = re.compile(
    r'<(h[234])((?:\s[^>]*)?)>(.*?)</\1\s*>',
    re.IGNORECASE | re.DOTALL,
)

_ID_RE = re.compile(r'''\bid\s*=\s*(["'])(.*?)\1''', re.IGNORECASE)
_CLASS_RE = re.compile(r'''\bclass\s*=\s*(["'])(.*?)\1''', re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')


def heading_text(inner_html):
    """标题里的纯文本：去掉内联标签、反转义实体、压平空白。"""
    txt = _TAG_RE.sub('', inner_html or '')
    txt = html_mod.unescape(txt)
    return re.sub(r'\s+', ' ', txt).strip()


def inject_heading_ids(html, prefix='sec'):
    """给 h2/h3/h4 补 id，并返回 (新html, 目录列表)。

    目录列表每项：{'level': 2, 'id': 'sec-1', 'text': '快速开始'}
    —— level 就是标题级别，前端按它做缩进。

    这个函数是**幂等**的：对已经注入过的 HTML 再跑一次，结果完全一样。
    所以详情页可以放心地对老文档（保存时还没有这个逻辑）再补一次。
    """
    if not html:
        return html or '', []

    used = set()
    toc = []
    counter = 0

    def repl(match):
        nonlocal counter

        tag = match.group(1).lower()
        attrs = match.group(2) or ''
        inner = match.group(3)

        text = heading_text(inner)
        if not text:
            return match.group(0)          # 空标题：不收录、也不动它

        id_match = _ID_RE.search(attrs)
        anchor = id_match.group(2).strip() if id_match else ''

        if anchor and anchor not in used:
            # 作者自己写的 id，原样保留
            open_tag = '<%s%s>' % (tag, attrs)
        else:
            # 缺失、或和前面的重名 -> 自动生成一个不冲突的
            while True:
                counter += 1
                candidate = '%s-%d' % (prefix, counter)
                if candidate not in used:
                    break
            anchor = candidate
            if id_match:
                attrs = attrs[:id_match.start()] + attrs[id_match.end():]
            open_tag = '<%s id="%s"%s>' % (tag, anchor, attrs)

        used.add(anchor)

        class_match = _CLASS_RE.search(attrs)
        classes = (class_match.group(2) if class_match else '').split()
        if 'no-toc' not in classes:
            toc.append({'level': int(tag[1]), 'id': anchor, 'text': text})

        return '%s%s</%s>' % (open_tag, inner, tag)

    return _HEADING_RE.sub(repl, html), toc


def extract_toc(html):
    """只取目录，不改 HTML。"""
    return inject_heading_ids(html)[1]
