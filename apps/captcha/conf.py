# apps/captcha/conf.py

import os

from django.conf import settings

_DEFAULTS = {
    # 背景图池目录
    'BG_DIR': None,
    # 统一画布尺寸 
    'WIDTH': 320,
    'HEIGHT': 160,
    # 拼图块边长
    'TILE_SIZE': 48,
    # 缺口 x 的随机范围   按画布宽度比例算
    'X_RATIO_MIN': 0.35,
    'X_RATIO_MAX': 0.75,
    # 容差 px
    'TOLERANCE': 8,
    # 有效期 s
    'EXPIRE_SECONDS': 120,
    # 通过滑块后签发的 ticket 有效期 s ,给用户填表的时间
    'TICKET_EXPIRE_SECONDS': 600,
    # 轨迹最多记录多少个采样点(只写日志用,暂不做行为判定)
    'MAX_TRACK_POINTS': 300,
}


class _Conf:
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in _DEFAULTS:
            raise AttributeError(f'未知的验证码配置项: CAPTCHA.{name}')

        value = (getattr(settings, 'CAPTCHA', None) or {}).get(name, _DEFAULTS[name])

        if name == 'BG_DIR' and not value:
            value = os.path.join(
                getattr(settings, 'BASE_DIR', ''),
                'apps', 'captcha', 'assets', 'captcha_bg',
            )
        return value


conf = _Conf()
