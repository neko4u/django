# apps/downloads/models.py
from django.db import models
from django.utils import timezone

from .versioning import display_version, padded_version


class ClientVersion(models.Model):
    """FRPClient 客户端版本登记表。

    版本号在库里统一存成**等长 6 位数字串**（规则见 versioning.py），
    所以 ``ORDER BY version DESC`` 的第一条就是最新版本，不用额外算。

    约定：
      - ``version`` 唯一 —— 同一个版本号不允许上传两次（要重传就带 replace 参数覆盖）
      - ``enable=False`` 表示「不展示」：前台查最新版本时会跳过它，
        直接访问该版本的下载地址也会被拒；记录本身保留，便于日后追溯
      - 只增不删：历史版本留在表里，用 enable 控制前台是否可见
    """

    version = models.CharField(
        max_length=6, unique=True,
        verbose_name='版本号(6位数字)',
        help_text='内部格式，如 1.0.1 存为 010001',
    )
    file_name = models.CharField(
        max_length=255,
        verbose_name='文件名称',
        help_text='文件在服务器客户端目录里的名字',
    )
    md5 = models.CharField(max_length=32, blank=True, default='', verbose_name='MD5')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小(字节)')
    enable = models.BooleanField(default=True, verbose_name='是否展示')
    uploaded_at = models.DateTimeField(default=timezone.now, verbose_name='上传日期')
    uploader_uid = models.CharField(
        max_length=64, blank=True, default='', verbose_name='上传者uid')

    class Meta:
        db_table = 'download_client_version'
        verbose_name = '客户端版本'
        verbose_name_plural = verbose_name
        ordering = ['-version']      # 固定长度数字串，倒序 = 从新到旧
        indexes = [
            models.Index(fields=['enable', 'version'], name='dl_ver_enable_ver'),
        ]

    def __str__(self):
        return 'v%s %s' % (self.display_version, self.file_name)

    # ---------------- 派生字段（不落库） ----------------

    @property
    def display_version(self):
        """给人看的简写：010001 -> 1.0.1"""
        return display_version(self.version)

    @property
    def padded_version(self):
        """补零写法：010001 -> 01.00.01"""
        return padded_version(self.version)

    @property
    def file_size_text(self):
        """人看的文件大小。"""
        size = self.file_size or 0
        if size < 1024:
            return '%d B' % size
        if size < 1024 * 1024:
            return '%.1f KB' % (size / 1024.0)
        if size < 1024 * 1024 * 1024:
            return '%.1f MB' % (size / 1048576.0)
        return '%.2f GB' % (size / 1073741824.0)
