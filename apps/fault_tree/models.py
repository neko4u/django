from django.db import models
from django.utils import timezone
from apps.login.models import UserInfo


class FaultTreePermission(models.Model):
    """故障树权限表 — 控制用户是否能访问和编辑"""
    user = models.OneToOneField(
        UserInfo,
        on_delete=models.CASCADE,
        related_name='fault_tree_perm',
        verbose_name='关联用户'
    )
    can_access = models.BooleanField(default=False, verbose_name='允许访问')
    can_edit = models.BooleanField(default=False, verbose_name='允许编辑')

    class Meta:
        db_table = 'fault_tree_permission'
        verbose_name = '故障树权限'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.user.account} — access={self.can_access} edit={self.can_edit}'


class FaultTreeManual(models.Model):
    """手册（顶层分类/领域）"""
    name = models.CharField(max_length=255, verbose_name='名称')
    description = models.TextField(default='', verbose_name='描述')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'fault_tree_manual'
        verbose_name = '故障树手册'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class FaultTreeDoc(models.Model):
    """文档（一棵故障树）"""
    manual = models.ForeignKey(
        FaultTreeManual,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='docs',
        verbose_name='所属手册'
    )
    title = models.CharField(max_length=255, verbose_name='标题')
    description = models.TextField(default='', verbose_name='描述')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'fault_tree_doc'
        verbose_name = '故障树文档'
        verbose_name_plural = verbose_name
        ordering = ['-updated_at']

    def __str__(self):
        return self.title


class FaultTreeCategory(models.Model):
    """分类"""
    name = models.CharField(max_length=255, verbose_name='名称')
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='父级分类'
    )
    doc = models.ForeignKey(
        FaultTreeDoc,
        on_delete=models.CASCADE,
        related_name='categories',
        verbose_name='所属文档'
    )

    class Meta:
        db_table = 'fault_tree_category'
        verbose_name = '故障树分类'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class FaultTreeNode(models.Model):
    """故障树节点"""
    doc = models.ForeignKey(
        FaultTreeDoc,
        on_delete=models.CASCADE,
        related_name='nodes',
        verbose_name='所属文档'
    )
    title = models.CharField(max_length=255, verbose_name='标题')
    content = models.TextField(default='', verbose_name='内容（HTML）')
    pos_x = models.FloatField(default=0, verbose_name='X 坐标')
    pos_y = models.FloatField(default=0, verbose_name='Y 坐标')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'fault_tree_node'
        verbose_name = '故障树节点'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f'[{self.id}] {self.title}'


class FaultTreeEdge(models.Model):
    """节点间的有向边"""
    doc = models.ForeignKey(
        FaultTreeDoc,
        on_delete=models.CASCADE,
        related_name='edges',
        verbose_name='所属文档'
    )
    source_node = models.ForeignKey(
        FaultTreeNode,
        on_delete=models.CASCADE,
        related_name='outgoing_edges',
        verbose_name='源节点'
    )
    target_node = models.ForeignKey(
        FaultTreeNode,
        on_delete=models.CASCADE,
        related_name='incoming_edges',
        verbose_name='目标节点'
    )
    label = models.CharField(max_length=255, default='', verbose_name='连线标签')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'fault_tree_edge'
        verbose_name = '故障树连线'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'[{self.source_node_id}] → [{self.target_node_id}] ({self.label})'


class FaultTreeComment(models.Model):
    """节点批注"""
    node = models.ForeignKey(
        FaultTreeNode,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='所属节点'
    )
    author = models.CharField(max_length=255, default='anonymous', verbose_name='作者')
    content = models.TextField(verbose_name='内容')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'fault_tree_comment'
        verbose_name = '节点批注'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.author}: {self.content[:50]}'
