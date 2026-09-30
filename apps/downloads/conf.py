# apps/downloads/conf.py
"""客户端下载 / 上传的配置（全部有默认值，settings.py 里不写 DOWNLOAD 段也能跑）。"""

import os

from django.conf import settings

_DEFAULTS = {
    # 服务器上客户端存放目录（绝对路径）。默认 <BASE_DIR>/downloads
    # 生产环境请指向"实际存放 FRPClient 的那个目录"
    'DIR': None,
    # 客户端下载到本地时的文件名（前沿固定用这个名字，跟服务器上的实际文件名无关）
    'FILE_NAME': 'SorielConnection.exe',
    # 同一个 IP 每小时最多下载几次（对客户端不可见，只在这里控制）
    'MAX_PER_IP_PER_HOUR': 10,
    # 后台单个上传文件的大小上限（字节），默认 300MB
    'UPLOAD_MAX_BYTES': 300 * 1024 * 1024,
    # 允许上传的扩展名（小写、不带点）；留空 () 表示不限制
    'ALLOWED_EXTENSIONS': ('exe', 'zip', '7z', 'rar', 'msi'),
    # 是否让 nginx 直接发文件（大文件推荐；需要配 nginx，见交付说明）
    'USE_X_ACCEL': False,
    # USE_X_ACCEL=True 时，nginx 里对应的 internal location 前缀
    'X_ACCEL_PREFIX': '/protected-download/',
}

class _Conf:
    def __getattr__(self, name):
        if name.startswith('_') or name not in _DEFAULTS:
            raise AttributeError(name)

        conf = getattr(settings, 'DOWNLOAD', None) or {}
        value = conf.get(name, _DEFAULTS[name])

        if name == 'DIR' and not value:
            value = os.path.join(getattr(settings, 'BASE_DIR', '') or '', 'downloads')
        return value

conf = _Conf()