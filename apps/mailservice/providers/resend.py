# apps/mailservice/providers/resend.py
"""方案 B：自有域名邮箱，Resend + Cloudflare。

Resend 负责发信，Cloudflare Email Routing 负责收信（可选）。
需要在 Resend 后台添加域名（可用二级域名，如 mail.example.com），
把它给出的 SPF / DKIM / MX 记录加到你的 DNS 解析里，等待验证通过。

依赖：不需要额外依赖，走 Django 原生 SMTP。
配置（见 settings.py 的 MAIL['RESEND']，值来自 /opt/config/django/project1settings.json）：
    smtp_host     smtp.resend.com
    smtp_port     587（STARTTLS）
    smtp_username  固定为 resend
    smtp_password  Resend 的 API Key（re_ 开头）
    from_email     必须是已验证域名下的地址，如 noreply@mail.example.com
"""

import logging

from .base import BaseMailProvider, MailConfigError, MailSendError

logger = logging.getLogger(__name__)


class ResendSMTPProvider(BaseMailProvider):
    name = 'resend'

    def __init__(self):
        from ..conf import mailconf

        cfg = mailconf.RESEND or {}
        self.host = (cfg.get('smtp_host') or 'smtp.resend.com').strip()
        self.port = int(cfg.get('smtp_port') or 587)
        self.username = (cfg.get('smtp_username') or 'resend').strip()
        self.password = (cfg.get('smtp_password') or '').strip()
        self.from_email = (cfg.get('from_email') or '').strip()
        self.sender_name = (cfg.get('from_name') or self.from_name).strip()
        self.use_tls = bool(cfg.get('use_tls', True))

        missing = [
            key for key, value in (
                ('smtp_password', self.password),
                ('from_email', self.from_email),
            ) if not value
        ]
        if missing:
            raise MailConfigError('Resend 配置缺失: ' + ', '.join(missing))

    def send_verification_code(self, to_email, code, scene, expire_minutes, accounts=None):
        """accounts：该邮箱绑定的登录帐号列表（找回密码场景用）。

        必须和 BaseMailProvider / codes.py 的调用签名保持一致，
        否则 codes.py 传 accounts= 时会直接 TypeError，整条发信链路失效。
        """
        from django.core.mail import EmailMultiAlternatives, get_connection

        subject, text, html = self.build_message(code, scene, expire_minutes, accounts)
        from_email = (
            f'{self.sender_name} <{self.from_email}>' if self.sender_name else self.from_email
        )

        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            use_tls=self.use_tls,
            timeout=15,
        )

        try:
            msg = EmailMultiAlternatives(
                subject, text, from_email, [to_email], connection=connection
            )
            msg.attach_alternative(html, 'text/html')
            sent = msg.send()
        except Exception as exc:
            self._raise_send_error(exc)

        if not sent:
            raise MailSendError('邮件发送失败，请稍后再试')

        logger.info('Resend SMTP 发送成功 to=%s scene=%s', to_email, scene)
        return ''

    @staticmethod
    def _raise_send_error(exc):
        """把 SMTP 的常见报错翻译成人话，方便上线时排查。"""
        raw = str(exc)
        logger.error('Resend SMTP 发送失败: %s', raw)
        hint = ''
        low = raw.lower()
        if '535' in raw or 'authentication' in low or 'invalid api key' in low:
            hint = '（认证失败：smtp_password 应为 Resend 的 API Key，且用户名固定是 resend）'
        elif '550' in raw or 'not verified' in low or 'domain' in low:
            hint = '（发信域名未验证：请确认 Resend 后台里域名状态已是 Verified，且 from_email 属于该域名）'
        elif 'timeout' in low or 'timed out' in low:
            hint = '（连接超时：确认服务器能出网访问 smtp.resend.com:587）'
        raise MailSendError('邮件发送失败，请稍后再试' + hint) from exc
