# apps/downloads/services.py
"""客户端版本表的读写逻辑 —— 后台页面、前台 findex、下载接口共用一套口径。

读：``latest_enabled / ``front_state / ``resolve_for_download
写：``store_upload / ``remove_file``（后台「上传新版本」用）
"""

import hashlib
import logging
import os
import re

from .conf import conf
from .models import ClientVersion

logger = logging.getLogger(__name__)

# ==================== 读 ====================

def latest_enabled():
    """版本号最大的「展示中」版本；没有则 ``None``。

    版本号是等长 6 位数字串，所以 ``order_by('-version') 的第一条就是最新，
    不需要额外排序或转换。
    """
    return ClientVersion.objects.filter(enable=True).order_by('-version').first()

def has_any():
    """表里有没有任何记录（不管展示与否）。"""
    return ClientVersion.objects.exists()

def all_versions():
    """后台列表用：全部版本，新的在前（Meta.ordering = ['-version']）。"""
    return ClientVersion.objects.all()

def version_by_six(six):
    """按内部 6 位版本号精确取一条。"""
    return ClientVersion.objects.filter(version=six).first()

def front_state():
    """前台当前处于哪种状态，返回 ``{'mode': ..., 'latest': ...}``：

    * 'legacy' —— 表里一条记录都没有：说明新功能还没用上，前台下载走旧的单文件
      （`conf.FILE_NAME`）。这样上线时不用先手工补数据，下载不会断。
    * 'ok'     —— 有可下载的最新版本。
    * 'off'    —— 有记录但全都被设成「不展示」：前台暂时没有可下载的版本。
    """
    latest = latest_enabled()
    if latest is not None:
        return {'mode': 'ok', 'latest': latest}
    if has_any():
        return {'mode': 'off', 'latest': None}
    return {'mode': 'legacy', 'latest': None}

def resolve_for_download(six=None):
    """下载时决定发哪一个版本，返回 ``(record, error)``。

    * 传了 ``six —— 指定版本：不存在 / 已下架都给错误
    * 没传       —— 取版本号最大的那个展示中版本（就是「最新版本」）

    ``(None, None) 表示表里一条记录都没有（legacy），调用方回落到旧单文件。
    """
    if six:
        record = version_by_six(six)
        if record is None:
            return None, '该版本不存在'
        if not record.enable:
            return None, '该版本已下架，请下载最新版本'
        return record, None

    state = front_state()
    if state['mode'] == 'ok':
        return state['latest'], None
    if state['mode'] == 'off':
        return None, '当前没有可下载的版本'
    return None, None

def file_path(record):
    """版本记录对应的磁盘文件绝对路径。"""
    return os.path.join(conf.DIR, os.path.basename(record.file_name))

# ==================== 写（后台上传用） ====================

# 文件名里只留这些字符，其余换成下划线：防掉 ../ 和中文空格造成的怪文件名
_SAFE = re.compile(r'[^0-9A-Za-z._\-]')

def versioned_filename(original_name, display):
    """把上传的文件名改成带版本号的名字，避免历史版本互相覆盖。

        SorielConnection.exe + 1.0.1 -> SorielConnection-1.0.1.exe

    文件名里已经带这个版本号时不重复追加（传 SorielConnection-1.0.1.exe 不会变成
    SorielConnection-1.0.1-1.0.1.exe）。
    """
    name = os.path.basename(str(original_name or '')).strip()
    stem, ext = os.path.splitext(name)
    stem = _SAFE.sub('_', stem).strip('._-') or 'client'
    ext = _SAFE.sub('', ext)

    suffix = '-%s' % display
    if stem.endswith(suffix):
        stem = stem[: -len(suffix)]
    return '%s%s%s' % (stem, suffix, ext)

def store_upload(uploaded, display):
    """把上传的文件写进 ``conf.DIR``，返回 ``(disk_name, md5, size)``。

    边写边算 MD5，52MB 的文件也不会整个读进内存。
    先写成 .part 再改名，避免半个文件被下载到。
    """
    os.makedirs(conf.DIR, exist_ok=True)
    disk_name = versioned_filename(getattr(uploaded, 'name', ''), display)
    final_path = os.path.join(conf.DIR, disk_name)
    tmp_path = final_path + '.part'

    digest = hashlib.md5()
    size = 0
    with open(tmp_path, 'wb') as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)

    os.replace(tmp_path, final_path)
    return disk_name, digest.hexdigest(), size

def remove_file(disk_name):
    """删掉版本目录里的一个文件（不存在就当没这回事）。"""
    if not disk_name:
        return
    path = os.path.join(conf.DIR, os.path.basename(disk_name))
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.info('已删除客户端旧文件 %s', path)
    except OSError as exc:
        # 删不掉不影响主流程，只是磁盘上多留一个文件
        logger.warning('删除客户端旧文件失败 %s: %s', path, exc)