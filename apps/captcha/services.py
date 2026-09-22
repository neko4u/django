# apps/captcha/services.py
import logging

from . import generator, store
from .conf import conf

logger = logging.getLogger(__name__)


def _summarize_track(track):
    """轨迹摘要，只写日志。后续要做行为判定（速度突变/停留点）可以在这里扩展。"""
    if not isinstance(track, list) or not track:
        return 'empty'
    return f'{len(track)}pts'


def create_challenge():
    """生成一次挑战，返回给前端的数据（不含正确答案）"""
    data = generator.make_captcha()
    token = store.new_token()
    store.save_challenge(token, data['target_x'], data['target_y'], data['bg_name'])

    return {
        'token': token,
        'bg': data['bg'],
        'tile': data['tile'],
        'y': data['target_y'],
        'tile_size': data['tile_size'],
        'width': data['width'],
        'height': data['height'],
        'track_width': data['track_width'],
        'expire_seconds': conf.EXPIRE_SECONDS,
    }


def verify_challenge(token, x, y=None, track=None, client_token=''):
    """校验拖动结果。

    返回 (ticket, error_message)：
      成功 -> (ticket 字符串, '')
      失败 -> (None, 面向用户的模糊提示)
    """
    if not token:
        return None, '验证已失效，请重新验证'

    try:
        challenge = store.pop_challenge(token)
    except store.CaptchaStoreError as exc:
        return None, str(exc)

    if not challenge:
        # token 不存在 / 过期 / 已被用过
        return None, '验证已失效，请重新验证'

    try:
        user_x = float(x)
    except (TypeError, ValueError):
        return None, '验证失败，请重新拖动'

    tolerance = conf.TOLERANCE
    delta = abs(user_x - challenge['x'])

    track = track if isinstance(track, list) else []
    if len(track) > conf.MAX_TRACK_POINTS:
        track = track[:conf.MAX_TRACK_POINTS]

    if delta > tolerance:
        logger.info(
            '滑块验证失败 cost=%.1f tolerance=%s bg=%s track=%s',
            delta, tolerance, challenge.get('bg'), _summarize_track(track),
        )
        return None, '验证失败，请重新拖动'

    try:
        ticket = store.new_ticket({
            'x': challenge['x'],
            'delta': round(delta, 2),
            'bg': challenge.get('bg', ''),
            'client_token': client_token,
            'track': _summarize_track(track),
        })
    except store.CaptchaStoreError as exc:
        return None, str(exc)

    logger.info(
        '滑块验证通过 cost=%.1f bg=%s track=%s',
        delta, challenge.get('bg'), _summarize_track(track),
    )
    return ticket, ''


def verify_ticket(request, field='slider_ticket'):
    """视图里调用：校验并**一次性消费**表单里的滑块 ticket。

    返回 (ok, error_message)
    """
    ticket = (request.POST.get(field) or '').strip()
    try:
        payload = store.consume_ticket(ticket)
    except store.CaptchaStoreError as exc:
        return False, str(exc)

    if not payload:
        return False, '请先完成安全验证'
    return True, ''
