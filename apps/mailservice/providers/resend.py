# apps/mailservice/providers/resend.py
"""方案 B：自有域名邮箱，Resend + Cloudflare。

Resend 负责发信，Cloudflare Email Routing 负责收信（可选）。
需要在 Resend 后台添加域名并把 DKIM / SPF / DMARC 记录加进 DNS。

依赖：不需要额外依赖，走 Django 原生 SMTP。
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

    def send_verification_code(self, to_email, code, scene, expire_minutes):
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
            logger.error(f'Resend SMTP 发送失败: {exc}')
            raise MailSendError('邮件发送失败，请稍后再试') from exc

        if not sent:
            raise MailSendError('邮件发送失败，请稍后再试')

        logger.info('Resend SMTP 发送成功')
        return ''
