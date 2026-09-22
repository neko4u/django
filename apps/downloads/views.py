# apps/downloads/views.py
"""客户端下载（只有一个下载接口，没有独立页面）。

限流：同一个 IP 每小时最多 MAX_PER_IP_PER_HOUR 次（默认 10），
计数用 Django cache（本项目是 Redis），key 按「IP + 当前小时」区分，过期自动归零。
限流对客户端不可见 —— 页面/接口都不暴露次数，触发上限时才给一句中性提示。
"""

import logging
import os
import time

from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_GET

from .conf import conf

logger = logging.getLogger(__name__)

_RATE_PREFIX = 'dl:ip:'

_BUSY_PAGE = (
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    '<title>提示</title></head>'
    '<body style="margin:0;min-height:100vh;display:flex;align-items:center;'
    'justify-content:center;font-family:system-ui,-apple-system,\'Segoe UI\','
    '\'Microsoft YaHei\',sans-serif;background:#f5f8ff;color:#5f6b7a;">'
    '<p style="font-size:15px;">下载服务繁忙，请稍后重试。</p>'
    '</body></html>'
)


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


def _file_path():
    return os.path.join(conf.DIR, conf.FILE_NAME)


@require_GET
def download_file(request):
    """GET /download/file/ —— 下载客户端（按 IP 限流）"""
    path = _file_path()
    if not os.path.isfile(path):
        logger.error(f'客户端文件不存在: {path}')
        raise Http404('客户端文件未就绪')

    ip = client_ip(request)
    ok, used = _consume(ip)

    if not ok:
        logger.warning(f'下载限流命中 ip={ip} used={used} limit={conf.MAX_PER_IP_PER_HOUR}')
        return HttpResponse(_BUSY_PAGE, status=429,
                            content_type='text/html; charset=utf-8')

    logger.info(f'客户端下载 ip={ip} 第 {used}/{conf.MAX_PER_IP_PER_HOUR} 次')

    # 交给 nginx 发文件（大文件推荐，需要配 nginx）
    if conf.USE_X_ACCEL:
        resp = HttpResponse()
        resp['X-Accel-Redirect'] = conf.X_ACCEL_PREFIX + conf.FILE_NAME
        resp['Content-Type'] = 'application/octet-stream'
        resp['Content-Disposition'] = f'attachment; filename="{conf.FILE_NAME}"'
        return resp

    resp = FileResponse(open(path, 'rb'),
                        as_attachment=True, filename=conf.FILE_NAME)
    resp['Content-Length'] = os.path.getsize(path)
    return resp
