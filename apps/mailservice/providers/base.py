# apps/mailservice/providers/base.py

SCENE_LABELS = {
    'change_pwd': '修改密码',
    'change_email': '修改邮箱',
    'reset_pwd': '重置密码',
}


class MailSendError(Exception):
    """邮件发送失败。message 可直接展示给用户（不包含敏感信息）"""


class MailConfigError(MailSendError):
    """配置缺失/错误。只在开发排查时有意义，不要向普通用户暴露细节"""


class BaseMailProvider:
    """所有邮件服务商的统一接口。

    业务代码只依赖 send_verification_code()，换服务商不影响上层。
    """

    name = 'base'

    @property
    def from_name(self):
        from ..conf import mailconf
        return (mailconf.FROM_NAME or 'Soriel').strip()

    def send_verification_code(self, to_email, code, scene, expire_minutes):
        raise NotImplementedError

    # ---------------- 共用：邮件内容 ----------------

    def build_message(self, code, scene, expire_minutes):
        """返回 (subject, text, html)"""
        label = SCENE_LABELS.get(scene, '身份验证')
        subject = f'【{self.from_name}】{label}验证码'

        text = (
            f'您的{label}验证码是：{code}\n\n'
            f'有效期 {expire_minutes} 分钟，请勿向任何人泄露。\n'
            f'如非本人操作，请忽略本邮件。'
        )

        html = (
            '<div style="font-family:system-ui,-apple-system,\'Segoe UI\',sans-serif;'
            'font-size:14px;color:#1a1a2e;line-height:1.75;">'
            f'<p>您好，您正在进行<b>{label}</b>操作。</p>'
            '<p>验证码：'
            '<span style="font-size:24px;font-weight:600;letter-spacing:5px;'
            f'color:#2b7de9;">{code}</span></p>'
            f'<p style="color:#5f6b7a;font-size:13px;">有效期 {expire_minutes} 分钟，'
            '请勿向任何人泄露。<br>如非本人操作，请忽略本邮件。</p>'
            '</div>'
        )

        return subject, text, html
