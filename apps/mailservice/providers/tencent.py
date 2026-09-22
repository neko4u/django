# apps/mailservice/providers/tencent.py
"""方案 A：腾讯云邮件推送（SES）API 方式。

为什么必须用 API：
  自 2026-03-02 起，新开通邮件推送的「个人实名认证」用户不再支持 SMTP 发信，
  只能用 API 或控制台发信。控制台无法自动化，所以验证码场景必须走 API。

发送方式有两种，按配置自动选择：
  1) 模板方式（**推荐**）：配置了 tencent_template_id 就用这个。
     腾讯云的自定义正文（Simple）可能需要联系商务经理单独开通权限，
     而模板只要在控制台建好并通过审核就能用，最稳。
  2) 自定义正文方式：没配 template_id 时用 Simple + HTML 正文。

依赖：pip install tencentcloud-sdk-python-ses
"""

import base64
import json
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

        # 模板方式（推荐）。留空则走 Simple 自定义正文。
        self.template_id = str(cfg.get('template_id') or '').strip()
        self.template_code_key = (cfg.get('template_code_key') or 'code').strip()
        self.template_minutes_key = (cfg.get('template_minutes_key') or 'minutes').strip()

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

    # ---------------- 内部：构造请求 ----------------

    def _build_request(self, models, to_email, code, scene, expire_minutes):
        subject, text, html = self.build_message(code, scene, expire_minutes)

        req = models.SendEmailRequest()
        req.FromEmailAddress = (
            f'{self.sender_name} <{self.from_email}>' if self.sender_name else self.from_email
        )
        req.Destination = [to_email]
        req.Subject = subject

        if self.template_id:
            # 模板方式：模板在控制台里已定义好，这里只传变量
            try:
                self._template_id_int = int(self.template_id)
            except (TypeError, ValueError):
                raise MailConfigError(
                    f'tencent_template_id 必须是数字，当前为 {self.template_id!r}'
                )
            req.Template = models.Template()
            req.Template.TemplateID = self._template_id_int
            req.Template.TemplateData = json.dumps({
                self.template_code_key: code,
                self.template_minutes_key: str(expire_minutes),
            }, ensure_ascii=False)
            return req, 'template'

        # 自定义正文方式
        req.Simple = models.Simple()
        # 腾讯云 SES 的 Simple.Html / Simple.Text 需要 base64 编码。
        # 如果发出去正文是空的或乱码，把下面两行改成直接赋值 html / text 再试一次。
        req.Simple.Html = base64.b64encode(html.encode('utf-8')).decode('ascii')
        req.Simple.Text = base64.b64encode(text.encode('utf-8')).decode('ascii')
        return req, 'simple'

    # ---------------- 对外接口 ----------------

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

        req, mode = self._build_request(models, to_email, code, scene, expire_minutes)

        cred = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile(endpoint=_ENDPOINT, reqTimeout=15)
        client = ses_client.SesClient(
            cred, self.region, ClientProfile(httpProfile=http_profile)
        )

        try:
            resp = client.SendEmail(req)
        except Exception as exc:
            raw = str(exc)
            logger.error(f'腾讯云 SES 发送失败（{mode} 方式）: {raw}')
            # 把最常见的两类错误翻译成人话，方便排查
            hint = ''
            if 'FailedOperation.NotAuthenticatedSender' in raw or 'not verified' in raw.lower():
                hint = '（发信地址未验证：请确认 SES 控制台里发信域名和发信地址都已是"验证通过"状态）'
            elif 'PermissionDenied' in raw or 'AuthFailure' in raw:
                hint = '（权限不足：自定义正文可能需要联系腾讯云商务经理开通，或改用模板方式）'
            raise MailSendError('邮件发送失败，请稍后再试' + hint) from exc

        message_id = getattr(resp, 'MessageId', '')
        logger.info(f'腾讯云 SES 发送成功（{mode} 方式）message_id={message_id}')
        return message_id
