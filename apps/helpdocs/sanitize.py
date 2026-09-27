# apps/helpdocs/sanitize.py
"""帮助中心 HTML 清洗 + Markdown 转换。
"""

import logging
import re

import bleach

logger = logging.getLogger(__name__)

# 允许保留的标签
ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'strong', 'b', 'em', 'i', 'u', 's', 'del', 'mark', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'a', 'img', 'span', 'div', 'section', 'figure', 'figcaption',
    'pre', 'code', 'blockquote',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

# 允许保留的属性
#   '*' 里的 id 给锚点用、class 给 no-toc 之类的约定用 —— 这两项必须放行，
#   否则详情页的左侧目录会静默失效。
ALLOWED_ATTRS = {
    '*': ['id', 'class'],
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'loading'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}

# 只允许这几种协议。相对路径（如 /media/help/...）没有协议，会原样保留。
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

# 整段匹配 <script>...</script> / <style>...</style>（含内容、大小写不敏感、跨行）
_SCRIPT_STYLE_RE = re.compile(
    r'<(script|style)\b[^>]*>.*?</\1\s*>', re.IGNORECASE | re.DOTALL
)


def drop_script_style(raw_html):
    """整段删掉 <script>/<style>（含内容）。"""
    return _SCRIPT_STYLE_RE.sub('', raw_html or '')


def clean_html(raw_html):
    """白名单清洗。输入管理员手写的 HTML，返回可安全直接输出的 HTML。"""
    if not raw_html:
        return ''
    return bleach.clean(
        drop_script_style(raw_html),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def html_to_markdown(safe_html):
    """把已清洗的 HTML 转成 Markdown。
    """
    if not safe_html:
        return ''
    try:
        import html2text
    except ImportError:
        logger.error('未安装 html2text，content_md 无法生成（pip install html2text）')
        return ''
    try:
        conv = html2text.HTML2Text()
        conv.body_width = 0        # 不折行（默认 78 字符会把中文切得很难看）
        conv.unicode_snob = True   # 保留中文原字符，不转成 HTML 实体
        return conv.handle(safe_html).strip()
    except Exception as exc:
        logger.error('HTML 转 Markdown 失败: %s', exc)
        return ''
