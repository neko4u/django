from django.db import models

class Conversation(models.Model):
    uid = models.ForeignKey(
        'login.UserInfo',
        on_delete=models.CASCADE,
        db_column='uid'
    )
    title = models.CharField(max_length=255, blank=True, default='新对话')
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conversation'
        ordering = ['-updated_at']

class Message(models.Model):
    ROLE_CHOICES = [
        ('user', '用户'),
        ('assistant', '助手'),
    ]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    model_name = models.CharField(max_length=100, blank=True, null=True, verbose_name='生成模型')
    reasoning_content = models.TextField(blank=True, default='', verbose_name='思考内容')
    

    class Meta:
        db_table = 'message'
        ordering = ['created_at']

class ConversationConfig(models.Model):
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        primary_key=True
    )
    model_name = models.CharField(max_length=100, default='deepseek-v4-flash')
    temperature = models.FloatField(default=0.7)
    max_tokens = models.IntegerField(default=24576)
    top_p = models.FloatField(default=1.0)
    presence_penalty = models.FloatField(default=0.0)
    frequency_penalty = models.FloatField(default=0.0)
    web_search_enabled = models.BooleanField(default=False, verbose_name='启用联网搜索')

class UserPermission(models.Model):
    uid = models.OneToOneField(
        'login.UserInfo',
        on_delete=models.CASCADE,
        primary_key=True,
        db_column='uid'
    )
    is_superadmin = models.BooleanField(default=False)
    can_access_chat = models.BooleanField(default=True)
    can_set_temperature = models.BooleanField(default=False)
    can_set_top_p = models.BooleanField(default=False)
    can_set_presence_penalty = models.BooleanField(default=False)
    can_set_frequency_penalty = models.BooleanField(default=False)
    can_set_max_tokens = models.BooleanField(default=False)

    class Meta:
        db_table = 'user_permission'

class LLMTask(models.Model):
    STATUS_CHOICES = [
        ('pending', '排队中'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    uid = models.ForeignKey(
        'login.UserInfo',
        on_delete=models.CASCADE,
        db_column='uid'
    )
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    model_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'llm_task'