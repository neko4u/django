# apps/mailservice/providers/console.py
"""临时方案：不真正发信，把验证码写进服务器日志。

用途：域名 / Resend 账号还没准备好之前，让「找回密码 / 修改密码 / 改邮箱」整条
流程可以先跑通并自测 —— 验证码不会发出邮件，而是打到 django 的日志里。

查看方式：
    tail -n 50 -f /path/to/your/django.log

正式方案（Resend）配好后，把配置里的 mail.provider 改成 'resend' 就自动切过去，
这个文件不用删，也不会再被执行。
"""

import logging

from .base import BaseMailProvider

logger = logging.getLogger(__name__)


class ConsoleMailProvider(BaseMailProvider):
    name = 'console'

    def send_verification_code(self, to_email, code, scene, expire_minutes):
        subject, text, html = self.build_message(code, scene, expire_minutes)

        logger.warning(
            '\n'
            '================ 邮件验证码（未真实发送，仅打印）================\n'
            '  场景  : %s\n'
            '  收件人: %s\n'
            '  验证码: %s\n'
            '  有效期: %s 分钟\n'
            '  主题  : %s\n'
            '===============================================================',
            scene, to_email, code, expire_minutes, subject,
        )

        return f'console:{scene}:{to_email}'
