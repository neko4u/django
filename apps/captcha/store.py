# apps/captcha/store.py
import logging
import secrets
import time

from django.core.cache import cache

from .conf import conf

logger = logging.getLogger(__name__)

_CHALLENGE_PREFIX = 'cap:slider:'
_TICKET_PREFIX = 'cap:ticket:'


class CaptchaStoreError(Exception):
    """状态存取失败（可直接展示给用户）"""


def new_token():
    return secrets.token_urlsafe(24)


def _save(key, payload, timeout):
    try:
        cache.set(key, payload, timeout=timeout)
    except Exception as exc:  # Redis 不可用
        logger.error(f'验证码状态写入缓存失败: {exc}')
        raise CaptchaStoreError('验证服务暂时不可用，请稍后重试') from exc


def _get(key):
    try:
        return cache.get(key)
    except Exception as exc:
        logger.error(f'验证码状态读取缓存失败: {exc}')
        raise CaptchaStoreError('验证服务暂时不可用，请稍后重试') from exc


def _delete(key):
    try:
        cache.delete(key)
    except Exception as exc:
        # 删除失败不影响主流程（有 TTL 兜底），只记警告
        logger.warning(f'验证码状态删除缓存失败: {exc}')


# ---------------- 挑战（答案） ----------------

def save_challenge(token, target_x, target_y, bg_name=''):
    """把正确答案写进缓存，绝不返回给前端"""
    _save(
        f'{_CHALLENGE_PREFIX}{token}',
        {
            'x': int(target_x),
            'y': int(target_y),
            'bg': bg_name,
            'ts': int(time.time()),
        },
        conf.EXPIRE_SECONDS,
    )


def pop_challenge(token):
    """取出并立即删除，保证一个 token 只能校验一次"""
    key = f'{_CHALLENGE_PREFIX}{token}'
    payload = _get(key)
    if payload is not None:
        _delete(key)
    return payload


# ---------------- Ticket（通过凭证） ----------------

def new_ticket(payload):
    token = secrets.token_urlsafe(24)
    _save(f'{_TICKET_PREFIX}{token}', payload, conf.TICKET_EXPIRE_SECONDS)
    return token


def consume_ticket(token):
    """一次性消费（登录/注册等防重放场景用）"""
    if not token:
        return None
    key = f'{_TICKET_PREFIX}{token}'
    payload = _get(key)
    if payload is None:
        return None
    _delete(key)
    return payload


def peek_ticket(token):
    """只读不删（改密码等允许多次提交的场景用）"""
    if not token:
        return None
    return _get(f'{_TICKET_PREFIX}{token}')


def drop_ticket(token):
    """主动作废"""
    if token:
        _delete(f'{_TICKET_PREFIX}{token}')
