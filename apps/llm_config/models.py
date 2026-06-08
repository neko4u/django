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


class ToolDefinition(models.Model):
    TOOL_TYPE_CHOICES = [
        ('internal', '内部函数'),
        ('external', '外部API'),
    ]
    name = models.CharField(max_length=100, unique=True, verbose_name='工具标识')
    display_name = models.CharField(max_length=100, verbose_name='显示名称')
    description = models.TextField(verbose_name='功能描述')
    parameters_schema = models.JSONField(default=dict, verbose_name='参数 Schema')
    tool_type = models.CharField(
        max_length=20,
        choices=TOOL_TYPE_CHOICES,
        default='internal',
        verbose_name='工具类型'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ToolConfig(models.Model):
    tool = models.ForeignKey(
        ToolDefinition,
        on_delete=models.CASCADE,
        verbose_name='工具'
    )
    key = models.CharField(max_length=100, verbose_name='配置键')
    value = models.TextField(verbose_name='配置值')
    description = models.CharField(max_length=255, blank=True, default='', verbose_name='说明')

    class Meta:
        unique_together = [['tool', 'key']]
        verbose_name = '工具配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.tool.name}: {self.key}"

class ModelToolBinding(models.Model):
    model_name = models.CharField(max_length=100, verbose_name='模型名称')
    tool = models.ForeignKey(
        ToolDefinition,
        on_delete=models.CASCADE,
        verbose_name='工具'
    )
    is_enabled = models.BooleanField(default=True, verbose_name='是否允许使用')
    # 该模型调用此工具时的默认参数（可与 ToolDefinition.parameters_schema 合并）
    default_parameters = models.JSONField(default=dict, blank=True, verbose_name='默认参数')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['model_name', 'tool']]
        verbose_name = '模型工具绑定'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.model_name} ← {self.tool.name}"

"""
deepseek tool calls的tool配置案例
tools = [
    {
    "type": "function",
    "function": {
        "name": "get_weather",
        "strict": true,
        "description": "Get weather of a location, the user should supply a location first.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                }
            },
            "required": ["location"],
            "additionalProperties": false
        }
    }
}
]

用户：询问现在的天气
模型：返回 function get_weather({location: 'Hangzhou'})
用户：调用 function get_weather({location: 'Hangzhou'})，并传给模型。
模型：返回自然语言，"The current temperature in Hangzhou is 24°C."
"""