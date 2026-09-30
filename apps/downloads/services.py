# apps/downloads/services.py
"""版本表的读取逻辑 —— 前台下载页和 findex 展示共用，保证两处口径一致。"""

from .models import ClientVersion


def latest_enabled():
    """版本号最大的「展示中」版本；没有则 ``None``。

    版本号是等长 6 位数字串，所以 ``order_by('-version')`` 的第一条就是最新，
    不需要额外排序或转换。
    """
    return ClientVersion.objects.filter(enable=True).order_by('-version').first()


def has_any():
    """表里有没有任何记录（不管展示与否）。"""
    return ClientVersion.objects.exists()


def front_state():
    """前台当前处于哪种状态，返回 ``{'mode': ..., 'latest': ...}``：

    * ``'legacy'`` —— 表里一条记录都没有：说明新功能还没用上，前台下载走旧的单文件
      （`conf.FILE_NAME`）。这样上线时不用先手工补数据，下载不会断。
    * ``'ok'``     —— 有可下载的最新版本。
    * ``'off'``    —— 有记录但全都被设成「不展示」：前台暂时没有可下载的版本。
    """
    latest = latest_enabled()
    if latest is not None:
        return {'mode': 'ok', 'latest': latest}
    if has_any():
        return {'mode': 'off', 'latest': None}
    return {'mode': 'legacy', 'latest': None}
