# apps/downloads/views.py
"""客户端下载（只有一个下载接口，没有独立页面）。

发哪个文件：默认发「版本号最大的展示中版本」，也就是后台列表里的「最新」。
可以带 ?v=010001 指定某个历史版本（内部 6 位格式），已下架的版本会被拒。
版本表还空着时（legacy）回落到旧的单文件 conf.FILE_NAME，保证上线不断下载。

限流：同一个 IP 每小时最多 MAX_PER_IP_PER_HOUR 次（默认 10），
计数用 Django cache（本项目是 Redis），key 按「IP + 当前小时」区分，过期自动归零。
限流对客户端不可见 —— 页面/接口都不暴露次数，触发上限时才给一句中性提示。
"""

import logging
import os
import time
from urllib.parse import quote

from django.core.cache import cache
from django.http import FileResponse, HttpResponse
from django.views.decorators.http import require_GET

from . import services
from .conf import conf
from .versioning import is_six

logger = logging.getLogger(__name__)

_RATE_PREFIX = 'dl:ip:'

def client_ip(request):
    """取真实客户端 IP（项目部署在 nginx 后面，REMOTE_ADDR 是 127.0.0.1）"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''

def _rate_key(ip):
    """按「IP + 当前小时」做 key，天然做到每小时自动重置"""
    return f'{_RATE_PREFIX}{ip}:{time.strftime("%Y%m%d%H", time.localtime())}'

def _consume(ip):
    """占用一次下载额度，返回 (是否放行, 本小时已用次数)。

    用 cache.add 做原子占位，避免并发下计数写丢。
    Redis 异常时**放行并记日志** —— 限流不应该把下载功能整个挡住。
    """
    limit = int(conf.MAX_PER_IP_PER_HOUR)
    key = _rate_key(ip)
    try:
        if cache.add(key, 1, timeout=3600):
            return True, 1
        used = cache.incr(key)
        if used > limit:
            return False, used
        return True, used
    except ValueError:
        # key 刚好过期了，重建计数
        cache.set(key, 1, timeout=3600)
        return True, 1
    except Exception as exc:
        logger.warning(f'下载限流计数失败，本次放行: {exc}')
        return True, 0

def _plain_page(text, status=200):
    """给客户端看的中性提示页（不暴露内部细节）。"""
    return HttpResponse(
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>提示</title></head>'
        '<body style="margin:0;min-height:100vh;display:flex;align-items:center;'
        'justify-content:center;font-family:system-ui,-apple-system,\'Segoe UI\','
        '\'Microsoft YaHei\',sans-serif;background:#f5f8ff;color:#5f6b7a;">'
        '<p style="font-size:15px;">%s</p></body></html>' % text,
        status=status,
        content_type='text/html; charset=utf-8',
    )

@require_GET
def download_file(request):
    """GET /download/file/ —— 下载客户端（按 IP 限流）。

    ?v=010001 指定历史版本（内部 6 位格式）；不传就是最新版本。
    """
    six = (request.GET.get('v') or '').strip()
    if six and not is_six(six):
        return _plain_page('版本号格式不对', status=400)

    record, err = services.resolve_for_download(six or None)
    if err:
        # 「表里有记录但全都不展示」也算这里，前台来下载就给中性提示
        logger.warning(f'客户端下载被拒: {err} v={six!r}')
        return _plain_page(err, status=404)

    if record is not None:
        path = services.file_path(record)
        # 下载到客户端的文件名也带版本号：SorielConnection-1.0.1.exe
        # （用服务器上的实际文件名，保证跟后台列表里「文件名称」一列完全一致）
        out_name = os.path.basename(path)
        version_text = record.display_version
        lookup = f'v{version_text}'
    else:
        # legacy：版本表还没数据，走旧的单文件，这时候没有版本号可用
        path = os.path.join(conf.DIR, conf.FILE_NAME)
        out_name = conf.FILE_NAME
        version_text = ''
        lookup = 'legacy'

    if not os.path.isfile(path):
        logger.error(f'客户端文件不存在: {path}')
        return _plain_page('客户端文件未就绪', status=404)

    ip = client_ip(request)
    ok, used = _consume(ip)

    if not ok:
        logger.warning(f'下载限流命中 ip={ip} used={used} limit={conf.MAX_PER_IP_PER_HOUR}')
        return _plain_page('下载服务繁忙，请稍后重试。', status=429)

    logger.info(f'客户端下载 ip={ip} 第 {used}/{conf.MAX_PER_IP_PER_HOUR} 次 '
                f'{lookup} file={os.path.basename(path)}')

    # 交给 nginx 发文件（大文件推荐，需要配 nginx）
    if conf.USE_X_ACCEL:
        resp = HttpResponse()
        resp['X-Accel-Redirect'] = conf.X_ACCEL_PREFIX + quote(os.path.basename(path))
        resp['Content-Type'] = 'application/octet-stream'
        resp['Content-Disposition'] = f'attachment; filename="{out_name}"'
        return resp

    resp = FileResponse(open(path, 'rb'), as_attachment=True, filename=out_name)
    resp['Content-Length'] = os.path.getsize(path)
    return resp