# apps/mailservice/conf.py
"""邮件服务配置读取。
全部配置写在 settings.py 的 MAIL 字典里（值来自 /opt/config/django/project1settings.json）。
"""

from django.conf import settings

_DEFAULTS = {
    # 'tencent'（腾讯云 SES API）或 'resend'（自有域名 SMTP）
    'PROVIDER': 'tencent',
    # 发件人显示名
    'FROM_NAME': 'Soriel',
    # 方案A：腾讯云邮件推送
    'TENCENT': {},
    # 方案B：Resend
    'RESEND': {},
    # 日发送上限（腾讯云免费额度 1000，Resend 每日 100）
    'DAILY_LIMIT': 1000,
    # 总发送上限（腾讯云免费额度是一次性的，用这个兜底）
    'TOTAL_LIMIT': 1000,
    # 验证码位数
    'CODE_LENGTH': 6,
    # 验证码有效期（秒）
    'CODE_EXPIRE_SECONDS': 600,
    # 同一邮箱两次发送的最小间隔（秒）
    'RESEND_INTERVAL': 60,
    # 同一邮箱 10 分钟内最多发送几次
    'MAX_PER_EMAIL_10MIN': 5,
    # 同一 IP 1 小时内最多发送几次
    'MAX_PER_IP_HOUR': 20,
    # 校验通过后签发的 ticket 有效期（秒）
    'TICKET_EXPIRE_SECONDS': 600,
}


class _MailConf:
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in _DEFAULTS:
            raise AttributeError(f'未知的邮件配置项: MAIL.{name}')
        return (getattr(settings, 'MAIL', None) or {}).get(name, _DEFAULTS[name])


mailconf = _MailConf()
