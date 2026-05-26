from django.db import models
from django.conf import settings
from django.core.validators import FileExtensionValidator

# Create your models here.

class UserPoint(models.Model):
    user = models.OneToOneField(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        primary_key=True,
        db_column='uid',
        verbose_name='用户'
    )
    points_balance = models.PositiveIntegerField(
        default=0,
        verbose_name='当前积分余额'
    )
    total_earned_points_balance = models.PositiveIntegerField(
        default=0,
        verbose_name='累计获取积分'
    )
    total_spent_points_balance = models.PositiveIntegerField(
        default=0,
        verbose_name='累计消耗积分'
    )
    version = models.IntegerField(
        default=0,
        verbose_name='乐观锁版本号'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    enable = models.BooleanField(default=True, verbose_name='是否启用')

    class Meta:
        verbose_name = '用户积分'
        verbose_name_plural = verbose_name

    def __str__(self):
        status = '启用' if self.enable else '停用'
        return f'{self.user_id} - {self.points_balance}积分'


class PointRecord(models.Model):
    class Direction(models.IntegerChoices):
        DEDUCTION = -1, '消耗'
        ADDITION = 1, '获取'

    class Scene(models.TextChoices):
        EXCHANGE = 'EXCHANGE', '兑换加速时长'
        REFUND = 'REFUND', '时长退款返还'
        MANUAL = 'MANUAL', '手动调整'
        SIGN_IN = 'SIGN_IN', '签到奖励'
        ACTIVITY = 'ACTIVITY', '活动赠送'
        CORRECTION = 'CORRECTION', '更正'

    user = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        db_column='uid',
        related_name='point_records',
        verbose_name='用户'
    )
    direction = models.IntegerField(choices=Direction.choices, verbose_name='积分是增加还是减少')
    scene = models.CharField(max_length=32, choices=Scene.choices, verbose_name='场景')
    amount = models.PositiveIntegerField(verbose_name='变动积分数（绝对值）')
    balance_after = models.PositiveIntegerField(verbose_name='变动后余额')
    activity = models.ForeignKey(
        'PointExchangeActivity',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='point_records',
        verbose_name='关联兑换活动'
    )

    # 暂时不需要
    # order_id = models.CharField(max_length=64, blank=True, default='', verbose_name='关联订单号')
    # session_id = models.CharField(max_length=64, blank=True, default='', verbose_name='关联会话ID')

    # 操作人 & IP（用于审计）
    operator = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='operator_uid',
        related_name='operated_point_records',
        verbose_name='操作人'
    )
    operator_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='操作人IP')

    detail_json = models.TextField(
        blank=True, default='{}',
        verbose_name='详细信息JSON',
        help_text='可存储额外信息,如兑换的时长秒数,操作人IP,ID等'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['scene', 'created_at']),
            # models.Index(fields=['order_id']),
        ]
        verbose_name = '积分变动记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.user_id} {self.get_direction_display()}{self.amount}积分'


class RewardType(models.TextChoices):
    FRP_TIME = 'FRP_TIME', 'FRP使用时长(秒)'
    TOKEN = 'TOKEN', 'Token'


class PointExchangeActivity(models.Model):
    name = models.CharField(max_length=128, verbose_name='活动名称')
    description = models.TextField(blank=True, default='', verbose_name='活动详情')
    cover_image = models.ImageField(
        upload_to='points_excActivity_covers/',
        default='points_excActivity_covers/default/default.jpg',
        null=True,
        blank=True,
        verbose_name="活动兑换封面",
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'png', 'jpeg']),
        ],
        help_text="允许的格式：jpg/png，最大2MB"
    )
    
    points_required = models.PositiveIntegerField(verbose_name='兑换需要积分')
    reward_type = models.CharField(
        max_length=32,
        choices=RewardType.choices,
        default=RewardType.FRP_TIME,
        verbose_name='奖励类型'
    )
    reward_value = models.PositiveIntegerField(
        default=0,
        verbose_name='奖励数量',
        help_text='例如 FRP时长(秒)、Token 数量等'
    )
    enable = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '积分兑换活动'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f'{self.name}（消耗{self.points_required}积分）'


class PointExchangeRecord(models.Model):
    user = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        db_column='uid',
        verbose_name='用户'
    )
    activity = models.ForeignKey(
        'PointExchangeActivity',
        on_delete=models.PROTECT,
        related_name='exchange_records',
        verbose_name='兑换活动'
    )
    points_deducted = models.PositiveIntegerField(verbose_name='实际扣除积分')
    reward_type = models.CharField(
        max_length=32,
        choices=RewardType.choices,
        verbose_name='奖励类型'
    )
    reward_value = models.PositiveIntegerField(verbose_name='兑换奖励数量')
    success = models.BooleanField(default=False, verbose_name='是否成功')
    fail_reason = models.CharField(
        max_length=256,
        blank=True,
        default='',
        verbose_name='失败原因'
    )
    
    detail_json = models.TextField(
        blank=True,
        default='{}',
        verbose_name='扩展信息JSON'
    )
    
    # 操作审计（可选，如需记录操作人IP等可保留，这里简化）
    # operator = models.ForeignKey(...)
    # operator_ip = models.GenericIPAddressField(...)
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='兑换时间')

    class Meta:
        verbose_name = '积分兑换记录'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['activity', 'created_at']),
            models.Index(fields=['success', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        status = '成功' if self.success else '失败'
        return f'{self.user_id} 兑换 {self.activity.name} ({self.get_reward_type_display()} x{self.reward_value}) - {status}'
