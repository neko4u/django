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



# ---------------------------------------------------------------------------
# 帮助中心（新）
#   表名一律 helpcenter_ 前缀，和上面旧的 help_document / help_node / help_user_like
#   在物理上分开；旧表保持原样，不要改动。
# ---------------------------------------------------------------------------

class HelpCenterDoc(models.Model):
    """帮助中心文档 —— 一篇 = 一页图文。"""

    docid = models.AutoField(primary_key=True, verbose_name='文档ID')
    title = models.CharField(max_length=200, default='', verbose_name='标题')

    # 管理员在后台直接编辑的 HTML，是唯一的内容源。
    # 展示时原样输出（保存前已做过白名单清洗，防存储型 XSS）。
    content_html = models.TextField(blank=True, default='', verbose_name='正文HTML')

    # 由 content_html 自动转换生成，主要用于导出 / 备份，不参与编辑。
    content_md = models.TextField(blank=True, default='', verbose_name='正文Markdown')

    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'helpcenter_doc'
        verbose_name = '帮助中心文档'
        verbose_name_plural = verbose_name
        ordering = ['-updated_at']

    def __str__(self):
        return f'[{self.docid}] {self.title or "(无标题)"}'


class HelpCenterImage(models.Model):
    """帮助中心图片。

    file_key 是文件在存储里的相对位置，例如：
        help/12/20260927-3f9a2c1b.png
    访问地址由 file_url 现算（MEDIA_URL + file_key），库里**不存** /media/... 前缀 ——
    将来换 CDN / 对象存储时只要改配置，不用全表改数据。
    """

    doc = models.ForeignKey(
        HelpCenterDoc,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='images',
        verbose_name='所属文档',
    )
    file_key = models.CharField(max_length=255, unique=True, verbose_name='存储相对路径')
    original_name = models.CharField(max_length=255, blank=True, default='',
                                     verbose_name='原始文件名')
    file_size = models.PositiveIntegerField(default=0, verbose_name='文件大小(字节)')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')

    class Meta:
        db_table = 'helpcenter_image'
        verbose_name = '帮助中心图片'
        verbose_name_plural = verbose_name
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.file_key

    @property
    def file_url(self):
        """给浏览器用的访问地址（派生值，不落库）。

        走 default_storage.url() 而不是手工拼 MEDIA_URL —— 这样将来把
        DEFAULT_FILE_STORAGE 换成 S3/OSS 时，这里自动返回 CDN 地址，零改动。
        """
        from django.core.files.storage import default_storage
        return default_storage.url(self.file_key)
