# apps/mailservice/codes.py
"""邮箱验证码：生成、限流、发送、校验、签发 ticket。

安全约定：
  1. 验证码只存 Redis，不落库明文
  2. 校验成功后立即删除（一次性）
  3. 按邮箱 / IP / 日总量多维限流
  4. 错误提示一律模糊化
"""

import logging
import secrets
import time

from django.core.cache import cache

from .conf import mailconf
from .providers import MailConfigError, MailSendError, get_mail_provider

logger = logging.getLogger(__name__)

# 允许的场景（view 层也要校验）
SCENES = ('change_pwd', 'change_email', 'reset_pwd')

_CODE_PREFIX = 'mail:code:'
_TICKET_PREFIX = 'mail:ticket:'
_LAST_SEND_PREFIX = 'mail:last:'
_EMAIL_CNT_PREFIX = 'mail:cnt:email:'
_IP_CNT_PREFIX = 'mail:cnt:ip:'
_DAILY_CNT_PREFIX = 'mail:cnt:daily:'
_TOTAL_CNT_KEY = 'mail:cnt:total'


class MailRateLimitError(Exception):
    """触发限流（可直接展示给用户）"""


# ---------------- 工具 ----------------

def normalize_email(email):
    return (email or '').strip().lower()


def mask_email(email):
    """日志与提示里给邮箱脱敏"""
    email = email or ''
    if '@' not in email:
        return '***'
    name, _, domain = email.partition('@')
    if len(name) <= 2:
        masked = (name[:1] or '*') + '*'
    else:
        masked = name[0] + '*' * (len(name) - 2) + name[-1]
    return f'{masked}@{domain}'


def generate_code():
    length = max(4, min(8, int(mailconf.CODE_LENGTH)))
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def _bump_counter(key, ttl):
    """计数器 +1，返回递增后的值（不存在的键会被原子创建）"""
    try:
        if cache.add(key, 1, timeout=ttl):
            return 1
        return cache.incr(key)
    except ValueError:
        # 键刚好过期了   重建
        cache.set(key, 1, timeout=ttl)
        return 1


def _check_limits(email, ip):
    """所有限流检查。返回本次发送占用的「间隔锁」key，发送失败时用来释放。"""
    now_ts = int(time.time())

    # 1 最小发送间隔
    last_key = f'{_LAST_SEND_PREFIX}{email}'
    if not cache.add(last_key, now_ts, timeout=mailconf.RESEND_INTERVAL):
        stored = cache.get(last_key) or now_ts
        wait = max(1, int(mailconf.RESEND_INTERVAL) - (now_ts - int(stored)))
        raise MailRateLimitError(f'请求过于频繁，请 {wait} 秒后再试')

    # 2 同一邮箱 10 分钟内次数
    email_cnt = _bump_counter(f'{_EMAIL_CNT_PREFIX}{email}', 600)
    if email_cnt > int(mailconf.MAX_PER_EMAIL_10MIN):
        raise MailRateLimitError('该邮箱请求次数过多，请稍后再试')

    # 3 同一 IP 1 小时内次数
    if ip:
        ip_cnt = _bump_counter(f'{_IP_CNT_PREFIX}{ip}', 3600)
        if ip_cnt > int(mailconf.MAX_PER_IP_HOUR):
            raise MailRateLimitError('当前网络请求次数过多，请稍后再试')

    # 4 每日额度
    day_ttl = 86400 - (now_ts % 86400)
    day_key = f'{_DAILY_CNT_PREFIX}{time.strftime("%Y%m%d", time.gmtime(now_ts))}'
    if _bump_counter(day_key, day_ttl) > int(mailconf.DAILY_LIMIT):
        raise MailRateLimitError('今日邮件额度已用完，请联系管理员')

    # 5 总配额
    #    给一个很长的 TTL，相当于永久计数
    if _bump_counter(_TOTAL_CNT_KEY, 60 * 60 * 24 * 365 * 20) > int(mailconf.TOTAL_LIMIT):
        raise MailRateLimitError('邮件总配额已用完，请联系管理员')

    return last_key


# ========= 发送 

def send_code(email, scene, ip=''):
    """发送验证码。失败时抛 MailSendError / MailRateLimitError"""
    email = normalize_email(email)
    if scene not in SCENES:
        raise MailSendError('未知的验证码场景')
    if not email or '@' not in email:
        raise MailSendError('邮箱格式不正确')

    last_key = _check_limits(email, ip)

    code = generate_code()
    expire_minutes = max(1, int(mailconf.CODE_EXPIRE_SECONDS) // 60)

    try:
        get_mail_provider().send_verification_code(
            email, code, scene, expire_minutes, accounts=accounts or []
        )
    except MailSendError:
        # 发送失败就把间隔锁释放掉
        try:
            cache.delete(last_key)
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            cache.delete(last_key)
        except Exception:
            pass
        logger.error(f'发送验证码邮件出现未预期异常 ({mask_email(email)}): {exc}')
        raise MailSendError('邮件发送失败，请稍后再试') from exc

    cache.set(
        f'{_CODE_PREFIX}{scene}:{email}',
        code,
        timeout=int(mailconf.CODE_EXPIRE_SECONDS),
    )
    logger.info(f'验证码已发送 scene={scene} to={mask_email(email)}')
    return code


# =========== 校验 

def verify_code(email, scene, code):
    """校验验证码。成功即删除，保证一次性。"""
    email = normalize_email(email)
    code = (code or '').strip()
    if scene not in SCENES or not code:
        return False

    key = f'{_CODE_PREFIX}{scene}:{email}'
    stored = cache.get(key)
    if not stored:
        return False
    if not secrets.compare_digest(str(stored), code):
        return False

    cache.delete(key)
    return True


# ============ Ticket 

def issue_ticket(email, scene, ttl=None):
    """验证码校验通过后签发的一次性凭证"""
    token = secrets.token_urlsafe(24)
    cache.set(
        f'{_TICKET_PREFIX}{token}',
        {'email': normalize_email(email), 'scene': scene, 'ts': int(time.time())},
        timeout=int(ttl or mailconf.TICKET_EXPIRE_SECONDS),
    )
    return token


def get_ticket(token, scene=None):
    """只读不删（改密码允许用户输错确认密码后重试）"""
    if not token:
        return None
    payload = cache.get(f'{_TICKET_PREFIX}{token}')
    if not payload:
        return None
    if scene and payload.get('scene') != scene:
        return None
    return payload


def drop_ticket(token):
    """用完后作废"""
    if token:
        try:
            cache.delete(f'{_TICKET_PREFIX}{token}')
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    'MailConfigError',
    'MailRateLimitError',
    'MailSendError',
    'SCENES',
    'drop_ticket',
    'generate_code',
    'get_ticket',
    'issue_ticket',
    'mask_email',
    'normalize_email',
    'send_code',
    'verify_code',
]
