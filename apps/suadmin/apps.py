from django.apps import AppConfig


class SuadminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.suadmin'          # 完整 Python 路径
    verbose_name = '后台管理'
