"""apps/rag/models.py — Wiki RAG 数据表（D1：不建 embedding 列）"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class RagPage(models.Model):
    """Wiki 原始页面（一页一行）"""

    page_id = models.IntegerField(primary_key=True, verbose_name='MediaWiki 页面ID')
    title = models.CharField(max_length=255, db_index=True, verbose_name='标题')
    revid = models.BigIntegerField(default=0, verbose_name='版本号')
    wiki_url = models.CharField(max_length=500, blank=True, default='', verbose_name='原文地址')
    updated_raw = models.CharField(max_length=200, blank=True, default='', verbose_name='页面更新文案')
    chunk_count = models.IntegerField(default=0, verbose_name='切片数')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rag_page'
        verbose_name = 'Wiki 页面'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.title}({self.page_id})'


class RagChunk(models.Model):
    """检索单元。embedding 列由 `manage.py rag_embed --init` 用原生 SQL 添加（避免迁移里写死维度）"""

    TYPE_CHOICES = [
        ('paragraph', '段落'),
        ('table_row', '表格行'),
        ('infobox', '信息框'),
    ]

    page = models.ForeignKey(
        RagPage, on_delete=models.CASCADE, related_name='chunks', db_column='page_id'
    )
    chunk_index = models.IntegerField(default=0, verbose_name='页内序号')
    content = models.TextField(verbose_name='正文')
    content_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='paragraph', verbose_name='类型'
    )
    header_path = models.CharField(max_length=300, blank=True, default='', verbose_name='章节路径')
    images = models.JSONField(default=list, blank=True, verbose_name='关联图片文件名')
    char_count = models.IntegerField(default=0, verbose_name='字符数')
    token_count = models.IntegerField(default=0, verbose_name='估算token')
    content_hash = models.CharField(max_length=64, db_index=True, blank=True, default='')
    search_vector = SearchVectorField(null=True, blank=True, verbose_name='全文检索向量')
    embedding_model = models.CharField(max_length=100, blank=True, default='')
    embedding_dim = models.IntegerField(default=0)
    revid = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rag_chunk'
        verbose_name = 'Wiki 切片'
        verbose_name_plural = verbose_name
        unique_together = [['page', 'chunk_index']]
        indexes = [GinIndex(fields=['search_vector'], name='rag_chunk_sv_gin')]

    def __str__(self):
        return f'{self.page_id}:{self.chunk_index}'


class RagQueryLog(models.Model):
    """每次提问的记录（后面接额度系统时直接用这张表算消耗）"""

    uid = models.IntegerField(db_index=True, verbose_name='用户ID')
    question = models.TextField(verbose_name='问题')
    answer = models.TextField(blank=True, default='', verbose_name='回答')
    mode = models.CharField(max_length=20, default='fts', verbose_name='检索模式')
    top_chunks = models.JSONField(default=list, blank=True, verbose_name='命中切片')
    hit_count = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    first_token_ms = models.IntegerField(default=0)
    model_name = models.CharField(max_length=100, blank=True, default='')
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    feedback = models.SmallIntegerField(default=0, verbose_name='反馈 1赞 -1踩')
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'rag_query_log'
        verbose_name = 'RAG 提问日志'
        verbose_name_plural = verbose_name


class RagTokenBalance(models.Model):
    """RAG 专用额度（与积分系统完全独立，后续开放兑换）"""

    uid = models.IntegerField(unique=True, verbose_name='用户ID')
    balance_units = models.BigIntegerField(default=0, verbose_name='余额(可负)')
    total_earned = models.BigIntegerField(default=0)
    total_spent = models.BigIntegerField(default=0)
    version = models.IntegerField(default=0, verbose_name='乐观锁')
    enable = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rag_token_balance'
        verbose_name = 'RAG 额度'
        verbose_name_plural = verbose_name


class RagTokenRecord(models.Model):
    """RAG 额度流水"""

    DIRECTION = [('earn', '获得'), ('spend', '消耗')]
    uid = models.IntegerField(db_index=True)
    direction = models.CharField(max_length=10, choices=DIRECTION)
    scene = models.CharField(max_length=40, default='', verbose_name='场景')
    amount = models.BigIntegerField(verbose_name='变动量')
    balance_after = models.BigIntegerField(default=0)
    business_id = models.CharField(max_length=64, unique=True, verbose_name='幂等键')
    request_id = models.CharField(max_length=64, blank=True, default='')
    detail = models.JSONField(default=dict, blank=True)
    operator_ip = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rag_token_record'
        verbose_name = 'RAG 额度流水'
        verbose_name_plural = verbose_name


class RagSetting(models.Model):
    """RAG 运行时配置（改完不用重启，缓存 60s 自动生效）"""

    key = models.CharField(max_length=100, primary_key=True)
    value = models.TextField(blank=True, default='')
    remark = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rag_setting'
        verbose_name = 'RAG 配置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.key
