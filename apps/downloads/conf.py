# apps/downloads/conf.py
"""客户端下载配置（全部有默认值，settings.py 里不用写 DOWNLOAD 段）。"""

import os

from django.conf import settings

_DEFAULTS = {
    # 服务器上客户端的文件名（下载下来也是这个名字）
    'FILE_NAME': 'SorielConnection.exe',
    # 文件所在目录（绝对路径）。默认 <BASE_DIR>/downloads
    'DIR': None,
    # 同一个 IP 每小时最多下载几次（对客户端不可见，只在这里控制）
    'MAX_PER_IP_PER_HOUR': 10,
    # 是否让 nginx 直接发文件（52MB 大文件推荐；需要配 nginx，见交付说明）
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
