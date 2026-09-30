# apps/downloads/versioning.py
"""版本号的解析 / 格式化（纯函数，不 import Django，方便单测）。

内部统一用**等长 6 位数字串**存储：

    1.0.1    -> 01.00.01 -> "010001"
    10.10.12 -> 10.10.12 -> "101012"

因为所有版本长度相同，所以**直接比字符串大小就等于比版本新旧**：

    "010001" < "010002" < "101012"

对外展示时再还原成简写： "010001" -> "1.0.1"。
"""

import re

SEGMENTS = 3        # 固定 3 段
SEG_LEN = 2         # 每段 2 位
DIGITS = SEGMENTS * SEG_LEN     # 6

# 中文输入法下很容易打出全角数字和全角小数点，先统一转半角再判断
_FULLWIDTH = str.maketrans(
    '０１２３４５６７８９．。',
    '0123456789..',
)

_RE_SIX = re.compile(r'^\d{6}$')            # 已经是内部格式
_RE_SEG = re.compile(r'^\d{1,2}$')          # 单段：1~2 位数字
_RE_NUMERIC_DOTTED = re.compile(r'^[0-9.]+$')   # 只含数字和点 -> 才值得逐段给提示


def parse_version(raw):
    """把管理员输入的版本号归一成 6 位数字串。

    返回 ``(six_digits, None)`` 或 ``(None, 错误提示)``。

    接受两种写法：

    * 简写 ``a.b.c`` —— 3 段、每段 1~2 位数字，如 ``1.0.1`` / ``01.00.01`` / ``10.10.12``
    * 内部 6 位格式 —— 如 ``010001``（等价于 ``1.0.1``）

    全角数字 / 全角小数点会先转成半角。
    """
    text = str(raw or '').translate(_FULLWIDTH).strip()
    if not text:
        return None, '版本号不能为空'

    # 已经是 6 位内部格式，直接用
    if _RE_SIX.match(text):
        return text, None

    if not _RE_NUMERIC_DOTTED.match(text):
        return None, ('版本号格式不对：应形如 1.0.1（3 段，用小数点隔开，'
                      '每段 1~2 位数字）')

    parts = text.split('.')
    if len(parts) != SEGMENTS:
        return None, ('版本号必须正好 %d 段（形如 1.0.1），当前是 %d 段'
                      % (SEGMENTS, len(parts)))

    for part in parts:
        if not _RE_SEG.match(part):
            return None, ('版本号每段只能是 1~2 位数字，当前有一段是 %r'
                          % (part or '(空)'))

    return ''.join(part.zfill(SEG_LEN) for part in parts), None


def is_six(value):
    """是不是合法的 6 位内部格式（库里存的就是这个）。"""
    return bool(_RE_SIX.match(str(value or '').strip()))


def display_version(six):
    """内部 6 位格式 -> 给人看的简写。

    ``"010001" -> "1.0.1"``；``"101012" -> "10.10.12"``。
    传入不是 6 位格式的值时原样返回（宁可显示得难看，也不要抛异常把页面搞挂）。
    """
    text = str(six or '').strip()
    if not _RE_SIX.match(text):
        return text
    return '.'.join(
        str(int(text[i:i + SEG_LEN])) for i in range(0, DIGITS, SEG_LEN)
    )


def padded_version(six):
    """内部 6 位格式 -> 补零写法。``"010001" -> "01.00.01"``"""
    text = str(six or '').strip()
    if not _RE_SIX.match(text):
        return text
    return '.'.join(text[i:i + SEG_LEN] for i in range(0, DIGITS, SEG_LEN))
