from django.db import models

class LLMProvider(models.Model):
    provider_name = models.CharField(max_length=100, unique=True, verbose_name='提供商名称')
    api_key = models.CharField(max_length=500, verbose_name='API密钥')
    base_url = models.URLField(max_length=500, verbose_name='API基础URL')
    model_list = models.JSONField(default=list, verbose_name='支持的模型列表')
    is_default = models.BooleanField(default=False, verbose_name='是否默认')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    max_context_tokens = models.IntegerField(default=8192, verbose_name='最大上下文 token 数')
    model_config = models.JSONField(default=dict, blank=True, verbose_name='模型详细配置')

    class Meta:
        verbose_name = 'LLM提供商'
        verbose_name_plural = 'LLM提供商'

    def __str__(self):
        return f"{self.provider_name} ({'默认' if self.is_default else '非默认'})"