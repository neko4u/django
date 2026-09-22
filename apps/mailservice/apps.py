from django.apps import AppConfig


class MailServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.mailservice'
    verbose_name = '邮件服务'
