from django.apps import AppConfig

class HelpdocsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.helpdocs'          # 完整的Python路径
    verbose_name = '帮助文档'