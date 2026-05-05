from django.db import models
from django.utils import timezone
from apps.login.models import UserInfo   # 导入自定义用户模型

class Document(models.Model):
    TYPE_CHOICES = (
        ('troubleshoot', '排错类型'),
        ('tutorial', '教程类型'),
    )
    docid = models.AutoField(primary_key=True, verbose_name='文档ID')
    title = models.CharField(max_length=200, verbose_name='标题')
    doc_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='tutorial', verbose_name='文档类型')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    views_count = models.IntegerField(default=0, verbose_name='浏览次数')
    likes_count = models.IntegerField(default=0, verbose_name='点赞次数')
    is_delete = models.BooleanField(default=False, verbose_name='逻辑删除')

    class Meta:
        db_table = 'help_document'
        verbose_name = '帮助文档'
        verbose_name_plural = '帮助文档'

    def __str__(self):
        return self.title

class Node(models.Model):
    nodeid = models.AutoField(primary_key=True, verbose_name='节点ID')
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='nodes', verbose_name='所属文档')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', verbose_name='父节点')
    title = models.CharField(max_length=200, verbose_name='节点标题')
    content = models.TextField(verbose_name='节点内容', help_text='支持HTML格式')
    order = models.IntegerField(default=0, verbose_name='排序权重')
    edge_description = models.CharField(max_length=255, blank=True, verbose_name='指向父节点的说明')

    class Meta:
        db_table = 'help_node'
        ordering = ['order']
        verbose_name = '文档节点'
        verbose_name_plural = '文档节点'

    def __str__(self):
        return self.title

class UserLike(models.Model):
    user = models.ForeignKey(UserInfo, on_delete=models.CASCADE, verbose_name='用户')
    document = models.ForeignKey(Document, on_delete=models.CASCADE, verbose_name='文档')
    liked_at = models.DateTimeField(auto_now_add=True, verbose_name='点赞时间')

    class Meta:
        db_table = 'help_user_like'
        unique_together = ('user', 'document')
        verbose_name = '用户点赞'
        verbose_name_plural = '用户点赞'