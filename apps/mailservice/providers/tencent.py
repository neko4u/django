# apps/mailservice/providers/tencent.py
"""方案 A：腾讯云邮件推送（SES）API 方式。

为什么必须用 API：
  自 2026-03-02 起，新开通邮件推送的「个人实名认证」用户不再支持 SMTP 发信，
  只能用 API 或控制台发信。控制台无法自动化，所以验证码场景必须走 API。

依赖：pip install tencentcloud-sdk-python-ses
"""

import base64
import logging

from .base import BaseMailProvider, MailConfigError, MailSendError

logger = logging.getLogger(__name__)

_ENDPOINT = 'ses.tencentcloudapi.com'


class TencentSESProvider(BaseMailProvider):
    name = 'tencent'

    def __init__(self):
        from ..conf import mailconf

        cfg = mailconf.TENCENT or {}
        self.secret_id = (cfg.get('secret_id') or '').strip()
        self.secret_key = (cfg.get('secret_key') or '').strip()
        self.region = (cfg.get('region') or 'ap-guangzhou').strip()
        self.from_email = (cfg.get('from_email') or '').strip()
        self.sender_name = (cfg.get('sender_name') or self.from_name).strip()

        missing = [
            key for key, value in (
                ('secret_id', self.secret_id),
                ('secret_key', self.secret_key),
                ('from_email', self.from_email),
            ) if not value
        ]
        if missing:
            # 只报缺哪些字段，不报值
            raise MailConfigError('腾讯云邮件推送配置缺失: ' + ', '.join(missing))

    def send_verification_code(self, to_email, code, scene, expire_minutes):
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.ses.v20201002 import models, ses_client
        except ImportError as exc:
            raise MailConfigError(
                '缺少依赖 tencentcloud-sdk-python-ses，请先执行 pip install'
            ) from exc

        subject, text, html = self.build_message(code, scene, expire_minutes)

        cred = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile(endpoint=_ENDPOINT, reqTimeout=15)
        client = ses_client.SesClient(
            cred, self.region, ClientProfile(httpProfile=http_profile)
        )

        req = models.SendEmailRequest()
        req.FromEmailAddress = (
            f'{self.sender_name} <{self.from_email}>' if self.sender_name else self.from_email
        )
        req.Destination = [to_email]
        req.Subject = subject
        req.Simple = models.Simple()
        # 腾讯云 SES 的 Simple.Html / Simple.Text 需要 base64 编码。
        # 如果发出去正文是空的或乱码，把下面两行改成直接赋值 html / text 再试一次。
        req.Simple.Html = base64.b64encode(html.encode('utf-8')).decode('ascii')
        req.Simple.Text = base64.b64encode(text.encode('utf-8')).decode('ascii')

        try:
            resp = client.SendEmail(req)
        except Exception as exc:
            logger.error(f'腾讯云 SES 发送失败: {exc}')
            raise MailSendError('邮件发送失败，请稍后再试') from exc

        message_id = getattr(resp, 'MessageId', '')
        logger.info(f'腾讯云 SES 发送成功 message_id={message_id}')
        return message_id
