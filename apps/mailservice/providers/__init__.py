# apps/mailservice/providers/__init__.py
"""邮件服务商工厂。

切换服务商只需要改 settings 里的 MAIL['PROVIDER']，
业务代码一行都不用动。
"""

from django.utils.module_loading import import_string

from .base import BaseMailProvider, MailConfigError, MailSendError

# 字符串路径，避免在 import 阶段就加载 tencentcloud 这类重依赖
_PROVIDERS = {
    'tencent': 'apps.mailservice.providers.tencent.TencentSESProvider',
    'resend': 'apps.mailservice.providers.resend.ResendSMTPProvider',
}


def get_mail_provider():
    """按配置返回服务商实例"""
    from ..conf import mailconf

    name = (mailconf.PROVIDER or 'tencent').strip().lower()
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
