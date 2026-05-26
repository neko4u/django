from django.db import models

# Create your models here.
class UserTimeBalance(models.Model):
    user = models.OneToOneField(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        primary_key=True,
        db_column='user_id',
        verbose_name='用户'
    )
    balance_seconds = models.PositiveIntegerField(default=0, verbose_name='剩余可用秒数')
    enable = models.BooleanField(default=True, verbose_name='是否启用')
    is_online = models.BooleanField(default=False, verbose_name='是否在线')
    current_session_id = models.CharField(max_length=64, blank=True, default='', verbose_name='当前会话ID')
    version = models.IntegerField(default=0, verbose_name='乐观锁版本号')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '用户时长表'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.user_id} - {self.balance_seconds}s'

class TimeChangeRecord(models.Model):
    class Direction(models.IntegerChoices):
        DEDUCTION = -1, '扣减'
        ADDITION = 1, '增加'

    class Scene(models.TextChoices):
        AUTO_SETTLE = 'AUTO_SETTLE', '自动结算'
        MANUAL = 'MANUAL', '人工调整'
        CORRECTION = 'CORRECTION', '差错更正'
        REWARD = 'REWARD', '活动赠送'
        REFUND = 'REFUND', '退款返还'
        EXCHANGED_FOR = 'EXCHANGED_FOR', '兑换获得'

    user = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        db_column='user_id',
        related_name='time_change_record',
        verbose_name='用户'
    )
    session_id = models.CharField(max_length=64, verbose_name='会话ID', blank=True, default='')
    direction = models.IntegerField(choices=Direction.choices, verbose_name='变动方向')
    amount_seconds = models.PositiveIntegerField(verbose_name='变动秒数（绝对值）')
    balance_after = models.PositiveIntegerField(verbose_name='变动后余额（秒）')
    scene = models.CharField(max_length=32, choices=Scene.choices, default=Scene.AUTO_SETTLE, verbose_name='场景')
    detail_json = models.TextField(blank=True, default='{}', verbose_name='详细信息JSON')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['session_id']),
        ]
        verbose_name = '时长变更记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        symbol = '-' if self.direction == self.Direction.DEDUCTION else '+'
        return f'{self.user_id} {symbol}{self.amount_seconds}s'