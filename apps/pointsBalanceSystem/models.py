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

    # 业务ID：用来把「一次业务动作」和「一条积分流水」一一对应起来，做幂等兜底。
    # 例如签到场景填的就是 SignInRecord.id。
    # ⚠️ 必须 null=True + default=None：PostgreSQL 里 NULL 互不相等，
    #    所以老流水和「不写 business_id 的场景」全都不受下面那条唯一约束影响；
    #    如果写成 default=''，所有老行的 (uid, scene, '') 会互相撞车，加约束直接失败。
    business_id = models.CharField(
        max_length=64, null=True, blank=True, default=None,
        verbose_name='业务ID',
        help_text='同一次业务动作只允许写一条流水（配合唯一约束做幂等）',
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['scene', 'created_at']),
            # models.Index(fields=['order_id']),
        ]
        constraints = [
            # 兜底：同一用户 + 同一场景 + 同一业务ID 只允许一条流水。
            # 这是「即使应用层判断出错，也不可能发两次积分」的最后一道防线。
            # ⚠️ business_id 为 NULL 的行不受影响（PG 里 NULL 互不相等）。
            models.UniqueConstraint(
                fields=['user', 'scene', 'business_id'],
                name='uniq_point_record_user_scene_business',
            ),
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

# ---------------------------------------------------------------------------
# 签到活动
# ---------------------------------------------------------------------------

class SignInActivity(models.Model):
    """签到活动配置。

    可以配置多条并存；「现在能不能签」= 启用 + 在有效期内（两端都包含）。
    见 is_active_at()。

    设计要求（与 SignInRecord 的唯一约束配合）：
      - 同一活动、同一用户、同一签到日期只能签一次
      - 想表达「长期活动」就把 end_at 填一个很远的日期
    """

    name = models.CharField(max_length=128, verbose_name='活动名称')
    description = models.TextField(blank=True, default='', verbose_name='活动说明')

    enable = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')

    # ⚠️ 判定口径是 start_at <= now <= end_at（两端都包含）。
    #    想要「一直有效到当天结束」就把 end_at 填成那天的 23:59（面板里的默认值）。
    #    千万不要把 end_at 填成 00:00 —— 那等于当天还没开始就结束。
    start_at = models.DateTimeField(verbose_name='活动开始时间')
    end_at = models.DateTimeField(verbose_name='活动结束时间')

    points_per_sign_in = models.PositiveIntegerField(
        default=0, verbose_name='每次签到赠送积分')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['enable', 'start_at', 'end_at']),
        ]
        constraints = [
            # 起止时间填反了 = 活动永远不可能生效，这种错误让数据库直接拦住
            models.CheckConstraint(
                check=models.Q(end_at__gt=models.F('start_at')),
                name='signin_activity_time_order',
            ),
        ]
        verbose_name = '签到活动'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '%s（每次 %d 积分）' % (self.name, self.points_per_sign_in)

    def is_active_at(self, now):
        """这个活动在 now 时刻是否生效：启用 + 在有效期内（两端都包含）。"""
        return bool(self.enable and self.start_at <= now <= self.end_at)


class SignInRecord(models.Model):
    """签到记录。

    ★ uniq_signin_activity_user_date 是整套防重逻辑的地基：
      服务层用 INSERT ... ON CONFLICT (activity_id, uid, sign_date) DO NOTHING
      RETURNING id 直接试插，靠「有没有返回行」判断本次是不是真的首次签到，
      完全不依赖「先查再插」，也不依赖捕获异常。

    这里**不存**连续签到天数/奖励积分：
      - 连续天数随时可以从本表推算（同一用户按 sign_date 倒序），不需要提前固化；
      - 等真要做连续奖励时再加字段，避免现在建一堆用不上的列。
    """

    user = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        db_column='uid',
        related_name='sign_in_records',
        verbose_name='用户',
    )
    activity = models.ForeignKey(
        SignInActivity,
        on_delete=models.PROTECT,
        related_name='sign_in_records',
        verbose_name='签到活动',
    )

    # sign_date 是「按服务端固定时区算出来的那个自然日」，不是 sign_time 的日期截断；
    # 唯一约束用的就是它，所以它是防重的关键列。
    sign_date = models.DateField(verbose_name='签到日期')
    sign_time = models.DateTimeField(verbose_name='签到时间')

    points_awarded = models.PositiveIntegerField(default=0, verbose_name='本次获得积分')
    operator_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='签到IP')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        ordering = ['-sign_time']
        constraints = [
            # ★ 同一活动 + 同一用户 + 同一签到日期 只能有一条。
            #   服务层的 ON CONFLICT 就以它作为冲突目标。
            #   ⚠️ 必须是**普通**唯一约束：不能加 condition、不能 DEFERRABLE，
            #      否则 ON CONFLICT (activity_id, uid, sign_date) 会报
            #      "there is no unique or exclusion constraint matching the ON CONFLICT specification"。
            models.UniqueConstraint(
                fields=['activity', 'user', 'sign_date'],
                name='uniq_signin_activity_user_date',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'sign_date']),
            models.Index(fields=['activity', 'sign_date']),
        ]
        verbose_name = '签到记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '%s %s +%d' % (self.user_id, self.sign_date, self.points_awarded)

