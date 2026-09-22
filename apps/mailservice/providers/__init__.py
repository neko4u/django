# apps/mailservice/providers/__init__.py
"""邮件服务商工厂。

切换服务商只需要改 settings 里的 MAIL['PROVIDER']（值来自 config JSON 的 mail.provider），
业务代码一行都不用动。

可选值：
  console —— 不真实发信，验证码打到服务器日志。域名/账号没准备好时先用这个自测。
  resend  —— Resend + 自有域名 SMTP。正式方案。
"""

from django.utils.module_loading import import_string

from .base import BaseMailProvider, MailConfigError, MailSendError

# 字符串路径，避免在 import 阶段就加载 SMTP 相关的重依赖
_PROVIDERS = {
    'console': 'apps.mailservice.providers.console.ConsoleMailProvider',
    'resend': 'apps.mailservice.providers.resend.ResendSMTPProvider',
}


def get_mail_provider():
    """按配置返回服务商实例"""
    from ..conf import mailconf

    name = (mailconf.PROVIDER or 'console').strip().lower()
    path = _PROVIDERS.get(name)
    if not path:
        raise MailConfigError(
            f'未知的邮件服务商 MAIL["PROVIDER"]={name}，可选：{", ".join(sorted(_PROVIDERS))}'
        )
    return import_string(path)()


__all__ = [
    'BaseMailProvider',
    'MailConfigError',
    'MailSendError',
    'get_mail_provider',
]
