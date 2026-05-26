import logging

from django.db import (
    transaction,
    models,
    DatabaseError
)

from apps.pointsBalanceSystem.models import (
    UserPoint,
    PointRecord,
    PointExchangeActivity,
    PointExchangeRecord
)

from apps.frpServer.models import (
    UserTimeBalance,
    TimeChangeRecord
)

logger = logging.getLogger(__name__)


class PointsExchangeService:

    MAX_RETRIES = 3

    def __init__(
        self,
        user,
        activity: PointExchangeActivity,
        quantity: int
    ):

        if not user:
            raise ValueError('用户不能为空')

        if not activity:
            raise ValueError('活动不能为空')

        if quantity <= 0:
            raise ValueError('兑换数量必须大于0')

        if not activity.enable:
            raise ValueError('兑换活动已关闭')

        self.user = user
        self.activity = activity
        self.quantity = quantity

        self.total_points = (
            activity.points_required * quantity
        )

        self.total_seconds = (
            activity.reward_value * quantity
        )

    def execute(self) -> PointExchangeRecord:

        for attempt in range(
            1,
            self.MAX_RETRIES + 1
        ):

            try:

                with transaction.atomic():

                    return self._do_exchange()

            except DatabaseError as e:

                logger.warning(
                    f'兑换乐观锁冲突，'
                    f'用户 {self.user.uid}，'
                    f'第 {attempt} 次重试，'
                    f'错误：{e}'
                )

                if attempt == self.MAX_RETRIES:

                    raise RuntimeError(
                        '系统繁忙，请稍后重试'
                    ) from e

        raise RuntimeError('兑换失败')

    def _do_exchange(self) -> PointExchangeRecord:

        # 锁定积分账户
        user_point, created = (
            UserPoint.objects
            .select_for_update()
            .get_or_create(
                user=self.user,
                defaults={
                    'points_balance': 0,
                    'total_earned_points_balance': 0,
                    'total_spent_points_balance': 0,
                    'enable': True
                }
            )
        )

        if not user_point.enable:
            raise ValueError('积分账户已停用')

        if user_point.points_balance < self.total_points:
            raise ValueError('积分不足')

        # 锁定时长账户
        time_balance, _ = (
            UserTimeBalance.objects
            .select_for_update()
            .get_or_create(
                user=self.user,
                defaults={
                    'enable': True
                }
            )
        )

        if not time_balance.enable:
            raise ValueError('时长账户已停用')

        old_point_version = user_point.version
        old_time_version = time_balance.version

        # 扣除积分
        updated = UserPoint.objects.filter(
            user=self.user,
            version=old_point_version
        ).update(

            points_balance=(
                models.F('points_balance')
                - self.total_points
            ),

            total_spent_points_balance=(
                models.F('total_spent_points_balance')
                + self.total_points
            ),

            version=old_point_version + 1
        )

        if updated == 0:
            raise DatabaseError('积分账户版本冲突')

        # 增加时长
        updated = UserTimeBalance.objects.filter(
            user=self.user,
            version=old_time_version
        ).update(

            balance_seconds=(
                models.F('balance_seconds')
                + self.total_seconds
            ),

            version=old_time_version + 1
        )

        if updated == 0:
            raise DatabaseError('时长账户版本冲突')

        # 刷新余额
        user_point.refresh_from_db()
        time_balance.refresh_from_db()

        # 创建积分流水
        PointRecord.objects.create(

            user=self.user,

            direction=PointRecord.Direction.DEDUCTION,

            scene=PointRecord.Scene.EXCHANGE,

            amount=self.total_points,

            balance_after=user_point.points_balance,

            activity=self.activity,

            detail_json={
                'reward_seconds': self.total_seconds,
                'quantity': self.quantity
            }
        )

        # 创建时长流水
        TimeChangeRecord.objects.create(

            user=self.user,

            direction=TimeChangeRecord.Direction.ADDITION,

            amount_seconds=self.total_seconds,

            balance_after=time_balance.balance_seconds,

            scene=TimeChangeRecord.Scene.EXCHANGED_FOR,

            detail_json={
                'activity_id': self.activity.id,
                'points_deducted': self.total_points
            }
        )

        # 创建兑换记录
        exchange_record = PointExchangeRecord.objects.create(

            user=self.user,

            activity=self.activity,

            points_deducted=self.total_points,

            reward_type=self.activity.reward_type,

            reward_value=self.total_seconds,

            success=True,

            detail_json={
                'quantity': self.quantity,
                'point_version_before': old_point_version,
                'time_version_before': old_time_version
            }
        )

        logger.info(
            f'用户 {self.user.uid} '
            f'成功兑换 '
            f'{self.total_seconds} 秒FRP时长，'
            f'消耗 {self.total_points} 积分'
        )

        return exchange_record