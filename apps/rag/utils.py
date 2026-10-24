"""apps/rag/utils.py — 图片地址推导 / SSE 封装 / 小工具"""
import hashlib
import json
from urllib.parse import quote

# 中文维基的图片文件实际存放在英文站（同一个 mediawiki 目录）
IMAGE_BASE = 'https://stardewvalleywiki.com/mediawiki/images'


def image_url(filename):
    """MediaWiki 存储路径：/images/{md5[0]}/{md5[0:2]}/{filename}

    已用真实样本验证：Parsnip.png -> d/db/Parsnip.png（与站上实际 URL 一致）
    """
    if not filename:
        return ''
    name = str(filename).strip().replace(' ', '_')
    if not name:
        return ''
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    return f'{IMAGE_BASE}/{h[0]}/{h[:2]}/{quote(name)}'


def sse(obj):
    """SSE 帧"""
    return 'data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n'


def est_tokens(text):
    return int(len(text or '') / 1.5) + 1


def client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
