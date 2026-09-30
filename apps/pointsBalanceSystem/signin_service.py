# apps/pointsBalanceSystem/signin_service.py
"""签到服务。

目标：**同一活动、同一用户、同一签到日期，只能签一次、只发一次积分。**

为什么这么写（三条"不用"）：

1. **不用「先查再插」**
   并发下两个请求会同时查到"今天没签过"，然后都去插 —— 唯一约束会拦住一个，
   但那是靠报错拦的，应用层等于没做判断。

2. **不靠捕获 IntegrityError 做控制流**
   PostgreSQL 里一个语句报错会让**整个事务**进入 aborted 状态，后续语句全部失败，
   必须先 ROLLBACK 才能继续 —— 用它当"正常分支"既慢又容易把外层事务搞脏。

3. **不用 bulk_create(ignore_conflicts=True)**
   Django 3.2 在 `ignore_conflicts=True` 时会主动关掉 RETURNING
   （源码 django/db/models/query.py：`if ... and not ignore_conflicts:`），
   插入成功也拿不到 pk —— 根本判不出"到底插没插"。

所以走原生 SQL，把判定权交给数据库的原子约束：

    INSERT INTO <表> (activity_id, uid, sign_date, sign_time, points_awarded, operator_ip, created_at)
    VALUES (...)
    ON CONFLICT (activity_id, uid, sign_date) DO NOTHING
    RETURNING id

  - **有返回值** → 这一次真的插进去了（首次签到）→ 才继续发积分
  - **返回 None** → 今天已签过（或并发下被别人抢先）→ 直接返回，不发积分

⚠️ 冲突目标必须**显式**写 `(activity_id, uid, sign_date)`。
   裸写 `ON CONFLICT DO NOTHING` 会把这张表上**所有**唯一约束的冲突一起吞掉：
   将来任何一条新约束（或某个字段的脏数据）一旦撞车，都会被伪装成「今天已签过」——
   用户看到"明天再来"，而你翻日志一条异常都找不到。

其它约定：

- `sign_date` 由**服务端**按固定时区计算（项目 `USE_TZ=False`，`timezone.now()` 返回
  naive 本地时间，"本地"即服务器 OS 时区；部署要求 Asia/Shanghai）。
  客户端传来的任何日期都不采信。
- 判定口径：`start_at <= now <= end_at`，**两端都包含**。
- 积分余额更新沿用项目范式：`select_for_update` + 乐观锁 `version` 比对；
  并且 `version` 必须 +1（否则 `UserPoint.version` 不再单调，其它流程的乐观锁会静默失效）。
- 积分流水用 `business_id = str(SignInRecord.id)` 做兜底 ——
  ⚠️ 千万不能填**活动ID**：那样同一个活动、同一个用户一辈子只能签一次，
  第二天插签到记录会成功，但写流水会撞唯一约束，从此再也发不出积分。

用法：

    from apps.pointsBalanceSystem.signin_service import SignInService

    result = SignInService(user, client_ip=ip).execute()
    if result['ok']:
        ...
    elif result['code'] == SignInService.ALREADY_SIGNED:
        ...
"""

import json
import logging

from django.db import DatabaseError, connection, models, transaction
from django.utils import timezone

from apps.pointsBalanceSystem.models import (
    PointRecord,
    SignInActivity,
    SignInRecord,
    UserPoint,
)

logger = logging.getLogger(__name__)


class SignInVersionConflict(Exception):
    """内部信号：积分账户乐观锁冲突，需要整体回滚后重试。

    刻意用异常而不是 return —— `with transaction.atomic()` 里 **return 会提交事务**，
    如果在"签到记录已插、积分还没加"的位置 return，就会把这个半成品提交上去，
    变成「有签到记录但没发积分」。抛异常才能让整个事务干净回滚。
    """


class SignInService:

    MAX_RETRIES = 3

    # ---- 结果码（前端按 code 分支，不要去解析 message）----
    SUCCESS = 'SUCCESS'                              # 签到成功，已发积分
    ALREADY_SIGNED = 'ALREADY_SIGNED'                # 今天已签过（正常状态，不是错误）
    NO_ACTIVITY = 'NO_ACTIVITY'                      # 没有可用 / 进行中的活动
    ACTIVITY_DISABLED = 'ACTIVITY_DISABLED'          # 活动已停用
    ACTIVITY_NOT_STARTED = 'ACTIVITY_NOT_STARTED'    # 活动尚未开始
    ACTIVITY_ENDED = 'ACTIVITY_ENDED'                # 活动已结束
    ACCOUNT_DISABLED = 'ACCOUNT_DISABLED'            # 积分账户已停用
    USER_INVALID = 'USER_INVALID'                    # 用户不存在 / 已注销
    VERSION_CONFLICT = 'VERSION_CONFLICT'            # 乐观锁连续冲突，请稍后重试

    def __init__(self, user, activity_id=None, client_ip=None, now=None):
        """
        :param user:        UserInfo 实例（必须由调用方从 session 取，**绝不接受前端传 uid**）
        :param activity_id: 指定活动 id；不传则自动选「当前进行中」的一个
        :param client_ip:   客户端 IP，None / '' 都会存成 NULL（PG 的 inet 不接受空串）
        :param now:        ⚠️ 仅供测试注入时间用，正常调用**不要传**
        """
        self.user = user
        self.activity_id = activity_id
        self.client_ip = (client_ip or '').strip() or None
        self.now = now

    # ------------------------------------------------------------------ 入口

    def execute(self):
        """执行签到。返回结果 dict（见模块 docstring 的字段说明）。"""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return self._do_sign_in()
            except (SignInVersionConflict, DatabaseError) as e:
                logger.warning(
                    '签到乐观锁冲突：用户 %s，第 %d/%d 次重试，%s: %s',
                    getattr(self.user, 'uid', None), attempt, self.MAX_RETRIES,
                    type(e).__name__, e,
                )
                if attempt == self.MAX_RETRIES:
                    return self._fail(self.VERSION_CONFLICT, '系统繁忙，请稍后重试')

        return self._fail(self.VERSION_CONFLICT, '系统繁忙，请稍后重试')

    # ------------------------------------------------------------------ 主流程

    def _do_sign_in(self):
        user = self.user
        if user is None or getattr(user, 'is_delete', False):
            return self._fail(self.USER_INVALID, '用户不存在或已注销')

        # ★ 日期只认服务端算出来的这个值
        now = self.now or timezone.now()
        sign_date = now.date()

        with transaction.atomic():

            act, err = self._pick_activity(now)
            if act is None:
                return err

            # 锁积分账户：
            #   - 让**同一用户**的并发签到在这里串行化（后到的会等前者提交）
            #   - 顺便拿到一份"不会被别人改动"的旧余额，用于精确算 balance_after
            user_point, _created = (
                UserPoint.objects
                .select_for_update()
                .get_or_create(
                    user=user,
                    defaults={
                        'points_balance': 0,
                        'total_earned_points_balance': 0,
                        'total_spent_points_balance': 0,
                        'enable': True,
                    },
                )
            )

            if not user_point.enable:
                return self._fail(self.ACCOUNT_DISABLED, '积分账户已停用',
                                  sign_date=sign_date.isoformat())

            points = int(act.points_per_sign_in or 0)

            # ★★ 核心：直接试插，靠"有没有返回行"判断本次是不是真的首次签到
            sign_id = self._insert_sign_record(act, sign_date, now, points)

            if sign_id is None:
                # 被数据库挡住了 —— 今天已经签过（或并发下被别人抢先）
                existing = (
                    SignInRecord.objects
                    .filter(user=user, activity=act, sign_date=sign_date)
                    .first()
                )
                return self._fail(
                    self.ALREADY_SIGNED, '今天已经签到过了，明天再来',
                    points=0,
                    today_points=existing.points_awarded if existing else 0,
                    sign_time=(existing.sign_time.strftime('%Y-%m-%d %H:%M:%S')
                               if existing else None),
                    balance=user_point.points_balance,
                    sign_date=sign_date.isoformat(),
                    activity_id=act.id,
                    activity_name=act.name,
                )

            # ---- 走到这里 = 真的插进去了，这次签到有效，开始发积分 ----

            old_version = user_point.version
            balance_after = user_point.points_balance + points

            updated = UserPoint.objects.filter(
                user=user,
                version=old_version,
            ).update(
                points_balance=models.F('points_balance') + points,
                total_earned_points_balance=(
                    models.F('total_earned_points_balance') + points),
                # ⚠️ 必须 +1：只加余额不推 version，会让全站的乐观锁静默失效
                version=old_version + 1,
            )

            if updated == 0:
                # 抛异常而不是 return —— 此时签到记录已经插了，必须整体回滚，
                # 否则会留下「有签到记录、没发积分」的半成品（且当天再也签不了）。
                raise SignInVersionConflict('积分账户版本冲突')

            # 积分流水：business_id 用签到记录 id 做幂等兜底
            PointRecord.objects.create(
                user=user,
                direction=PointRecord.Direction.ADDITION,
                scene=PointRecord.Scene.SIGN_IN,
                amount=points,
                balance_after=balance_after,
                business_id=str(sign_id),
                operator_ip=self.client_ip,
                detail_json=json.dumps({
                    'sign_record_id': sign_id,
                    'activity_id': act.id,
                    'activity_name': act.name,
                    'sign_date': sign_date.isoformat(),
                }, ensure_ascii=False),
            )

            logger.info(
                '签到成功：用户 %s，活动 %s(#%s)，日期 %s，+%d 积分，余额 %d，记录 #%s',
                user.uid, act.name, act.id, sign_date, points, balance_after, sign_id,
            )

            return self._ok(
                message='签到成功，获得 %d 积分' % points,
                points=points,
                balance=balance_after,
                sign_date=sign_date.isoformat(),
                sign_time=now.strftime('%Y-%m-%d %H:%M:%S'),
                sign_record_id=sign_id,
                activity_id=act.id,
                activity_name=act.name,
            )

    # ------------------------------------------------------------------ 选活动

    def _pick_activity(self, now):
        """返回 (activity, None) 或 (None, 现成的失败结果)。"""
        if self.activity_id:
            act = SignInActivity.objects.filter(pk=self.activity_id).first()
            if act is None:
                return None, self._fail(self.NO_ACTIVITY, '签到活动不存在')
            if not act.enable:
                return None, self._fail(self.ACTIVITY_DISABLED, '活动已停用',
                                        activity_id=act.id, activity_name=act.name)
            if now < act.start_at:
                return None, self._fail(self.ACTIVITY_NOT_STARTED, '活动尚未开始',
                                        activity_id=act.id, activity_name=act.name,
                                        start_at=act.start_at.strftime('%Y-%m-%d %H:%M:%S'))
            if now > act.end_at:
                return None, self._fail(self.ACTIVITY_ENDED, '活动已结束',
                                        activity_id=act.id, activity_name=act.name,
                                        end_at=act.end_at.strftime('%Y-%m-%d %H:%M:%S'))
            return act, None

        # 没指定就自动挑「启用 且 在有效期内」里最新创建的一个
        act = (
            SignInActivity.objects
            .filter(enable=True, start_at__lte=now, end_at__gte=now)
            .order_by('-created_at', '-id')
            .first()
        )
        if act is None:
            return None, self._fail(self.NO_ACTIVITY, '当前没有进行中的签到活动')
        return act, None

    # ------------------------------------------------------------------ 原生 SQL

    def _insert_sign_record(self, act, sign_date, now, points):
        """尝试插入签到记录。**真的插进去**返回新 id，冲突（今天已签）返回 None。

        用原生 SQL 而不是 ORM，是因为 ORM 拿不到「DO NOTHING 到底有没有插进去」这个信息
        （详见模块 docstring 第 3 条）。

        ⚠️ 表名必须用 quote_name 拼：app_label 是 `pointsBalanceSystem`（保留大小写），
           PG 里的表名就是 `pointsBalanceSystem_signinrecord`，手写小写会 relation does not exist。
        ⚠️ created_at 是 auto_now_add，那只在 ORM 里生效，原生 SQL 必须自己给值。
        """
        table = connection.ops.quote_name(SignInRecord._meta.db_table)
        sql = (
            'INSERT INTO %s '
            '(activity_id, uid, sign_date, sign_time, points_awarded, operator_ip, created_at) '
            'VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s) '
            'ON CONFLICT (activity_id, uid, sign_date) DO NOTHING '
            'RETURNING id' % table
        )
        with connection.cursor() as cur:
            cur.execute(sql, [
                act.id,
                self.user.uid,
                sign_date,
                now,
                points,
                self.client_ip,
                now,
            ])
            row = cur.fetchone()

        return row[0] if row else None

    # ------------------------------------------------------------------ 结果构造

    def _ok(self, message, **extra):
        result = {'ok': True, 'code': self.SUCCESS, 'message': message}
        result.update(extra)
        return result

    def _fail(self, code, message, **extra):
        result = {'ok': False, 'code': code, 'message': message}
        result.update(extra)
        return result

    # ------------------------------------------------------------------ 只读辅助

    @staticmethod
    def current_activity(now=None):
        """当前生效的签到活动（启用 + 在有效期内），没有就返回 None。"""
        now = now or timezone.now()
        return (
            SignInActivity.objects
            .filter(enable=True, start_at__lte=now, end_at__gte=now)
            .order_by('-created_at', '-id')
            .first()
        )

    @classmethod
    def today_status(cls, user, now=None):
        """给前端卡片用：当前活动 + 今天签没签 + 今天拿了多少积分 + 余额。

        纯读，不改任何数据。
        """
        now = now or timezone.now()
        today = now.date()

        act = cls.current_activity(now)
        point = UserPoint.objects.filter(user=user).first()

        data = {
            'activity': None,
            'signed_today': False,
            'today_points': 0,
            'sign_time': None,
            'sign_date': today.isoformat(),
            'balance': point.points_balance if point else 0,
            'account_enable': bool(point.enable) if point else True,
        }

        if act is None:
            return data

        data['activity'] = {
            'id': act.id,
            'name': act.name,
            'description': act.description,
            'points_per_sign_in': act.points_per_sign_in,
            'start_at': act.start_at.strftime('%Y-%m-%d %H:%M:%S'),
            'end_at': act.end_at.strftime('%Y-%m-%d %H:%M:%S'),
        }

        rec = (
            SignInRecord.objects
            .filter(user=user, activity=act, sign_date=today)
            .first()
        )
        if rec is not None:
            data['signed_today'] = True
            data['today_points'] = rec.points_awarded
            data['sign_time'] = rec.sign_time.strftime('%Y-%m-%d %H:%M:%S')

        return data
