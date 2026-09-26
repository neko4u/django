# apps/suadmin/models.py
from django.db import models
from django.utils import timezone


class SuadminAdmin(models.Model):
    """后台管理员 —— 后台权限的唯一来源。

    判定规则（三层，全部通过才放行）：
      1) 本表里没有这条记录      -> 无任何后台权限，连 /suadmin/ 都进不去
      2) enable=False           -> 同上（停用即等于移除，但保留记录便于追溯）
      3) is_super=True          -> 所有权限直接通过（新增功能不用补勾权限）
         否则                   -> permissions 里必须含对应权限码

    设计约定：
      - 用 user 的 uid 直接作主键，一个人只能有一条记录
      - 停用时**不删记录**，方便日后查"是谁、什么时候被停的"
      - permissions 存权限码字符串列表，权限码集中在
        apps/suadmin/permissions.py 定义，不要在别处散落字符串
    """

    uid = models.OneToOneField(
        'login.UserInfo',
        to_field='uid',
        db_column='uid',
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='suadmin_admin',
        verbose_name='用户',
    )
    enable = models.BooleanField(default=True, verbose_name='是否启用')
    is_super = models.BooleanField(default=False, verbose_name='超级管理员')
    permissions = models.JSONField(default=list, blank=True, verbose_name='权限码列表')
    note = models.CharField(max_length=255, blank=True, default='', verbose_name='备注')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'suadmin_admin'
        verbose_name = '后台管理员'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        role = '超级管理员' if self.is_super else '管理员'
        return f'{self.uid} {role} enable={self.enable}'

    # ---------------- 权限判定 ----------------

    def has_perm(self, code):
        """是否拥有某个权限码。"""
        if not self.enable:
            return False
        if self.is_super:
            return True
        return code in (self.permissions or [])
