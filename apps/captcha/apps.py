from django.apps import AppConfig


class CaptchaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.captcha'
    verbose_name = '滑块验证码'
