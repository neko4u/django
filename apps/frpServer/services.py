from apps.login.models import FrpPermission
from apps.login.services import JwtService

def authenticate_user(request):
    """
    从 session 或 JWT token 中统一提取 user_id。
    成功返回 user_id (str/int)，失败返回 None。
    """
    # 方式1: session 登录
    if request.session.get('is_logged_in'):
        info = request.session.get('info', {})
        uid = info.get('uid') or info.get('id')
        if uid:
            return uid

    # 方式2: JWT token 登录
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        try:
            payload = JwtService.verify_token(token)
            if payload:
                return payload.get('user_id') or payload.get('uid') or payload.get('id')
        except Exception:
            pass  # 校验失败统一在外部处理
    return None


def check_frp_permission(user_id, perm_name='can_access'):
    """
    检查用户是否拥有指定的 FRP 权限。
    返回 (success: bool, result: FrpPermission or error_message: str)
    """
    try:
        perm = FrpPermission.objects.get(user_id=user_id)
    except FrpPermission.DoesNotExist:
        return False, '未配置权限'

    if not perm.can_access:
        return False, '无FRP权限'

    if perm_name and not getattr(perm, perm_name, False):
        return False, '权限不足'

    return True, perm





# 设计
#   - 会话开始：DB 建记录，redis 写会话 hash（TTL 24h 兜底，孤儿由巡检清理）
#   - 心跳(30s)：只写 redis last_heartbeat，零 DB 写
#   - 掉线判定：巡检读 redis last_hb，超 120s -> end_ts = last_hb+120 结算
#   - 到期判定：DB 扫 stop_time<=now
#   - 充值：add_time 加余额 + stop_time 顺延，不产生中途结算
#
# redis 结构：
#   frp:session:{uid}  -> hash {session_id, start_ts, stop_time, last_heartbeat}
#   frp:online_uids    -> set 在线 uid（对账巡检用）

import time
import uuid
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import transaction, models
from django.db.utils import DatabaseError
from django.utils import timezone

from .models import UserTimeBalance, TimeChangeRecord, FrpSessionRecord

SESSION_TTL = 120            # 心跳超时阈值（秒），超过判掉线
HEARTBEAT_INTERVAL = 30      # 客户端心跳周期（秒），仅供参考/校验
REDIS_SESSION_EXPIRE = 86400  # redis 会话 key 兜底 TTL（24h），孤儿 key 由巡检清理


def _redis():
    return cache.client.get_client()


def _session_key(uid):
    return f'frp:session:{uid}'


def _to_ts(dt):
    """datetime(naive本地) -> int 秒"""
    return int(dt.timestamp())


def _from_ts(ts):
    """int 秒 -> datetime(naive本地, 与 USE_TZ=False 一致)"""
    return datetime.fromtimestamp(ts)


def _now():
    return timezone.now()


def _write_redis_session(uid, session_id, start_ts, stop_time, last_heartbeat):
    r = _redis()
    key = _session_key(uid)
    pipe = r.pipeline()
    pipe.hset(key, mapping={
        'session_id': session_id,
        'start_ts': _to_ts(start_ts),
        'stop_time': _to_ts(stop_time),
        'last_heartbeat': _to_ts(last_heartbeat),
    })
    pipe.expire(key, REDIS_SESSION_EXPIRE)
    pipe.sadd('frp:online_uids', str(uid))
    pipe.execute()


def _clear_redis_session(uid):
    r = _redis()
    pipe = r.pipeline()
    pipe.delete(_session_key(uid))
    pipe.srem('frp:online_uids', str(uid))
    pipe.execute()


# 加时长

def add_time(user, seconds, scene, detail_json=None, *, extend_session=True):

    if seconds <= 0:
        raise ValueError('增加秒数必须为正')

    with transaction.atomic():
        tb, _ = UserTimeBalance.objects.select_for_update().get_or_create(
            user=user, defaults={'enable': True})
        if not tb.enable:
            raise ValueError('时长账户已停用')

        old_version = tb.version
        updated = UserTimeBalance.objects.filter(
            user=user, version=old_version
        ).update(
            balance_seconds=models.F('balance_seconds') + seconds,
            version=old_version + 1,
        )
        if updated == 0:
            raise DatabaseError('version校验失败,请重试')
        tb.refresh_from_db()

        TimeChangeRecord.objects.create(
            user=user,
            direction=TimeChangeRecord.Direction.ADDITION,
            amount_seconds=seconds,
            balance_after=tb.balance_seconds,
            scene=scene,
            detail_json=detail_json or '{}',
        )

        if extend_session:
            session = FrpSessionRecord.objects.filter(
                user=user, status='active').first()
            if session:
                session.stop_time = session.stop_time + timedelta(seconds=seconds)
                session.save(update_fields=['stop_time'])
                r = _redis()
                key = _session_key(user.uid)
                if r.exists(key):
                    r.hset(key, 'stop_time', _to_ts(session.stop_time))
                    r.expire(key, REDIS_SESSION_EXPIRE)

    return tb.balance_seconds


# 会话开始

def start_session(user, now=None):
    now = now or _now()

    existing = FrpSessionRecord.objects.filter(
        user=user, status='active').order_by('-start_ts').first()
    if existing:
        _write_redis_session(
            user.uid, existing.session_id, existing.start_ts,
            existing.stop_time, now)
        UserTimeBalance.objects.filter(user=user).update(
            is_online=True, current_session_id=existing.session_id)
        tb, _ = UserTimeBalance.objects.get_or_create(user=user)
        return {
            'session_id': existing.session_id,
            'balance_seconds': tb.balance_seconds,
            'stop_time': existing.stop_time,
            'reused': True,
        }

    with transaction.atomic():
        tb, _ = UserTimeBalance.objects.select_for_update().get_or_create(
            user=user, defaults={'enable': True})
        if not tb.enable:
            raise ValueError('时长账户已停用')
        if tb.balance_seconds <= 0:
            raise ValueError('账户余额不足，请先充值')

        session_id = uuid.uuid4().hex
        start_ts = now
        stop_time = now + timedelta(seconds=tb.balance_seconds)

        FrpSessionRecord.objects.create(
            session_id=session_id,
            user=user,
            start_ts=start_ts,
            stop_time=stop_time,
            status='active',
        )
        UserTimeBalance.objects.filter(user=user).update(
            is_online=True, current_session_id=session_id)

    _write_redis_session(user.uid, session_id, start_ts, stop_time, now)

    return {
        'session_id': session_id,
        'balance_seconds': tb.balance_seconds,
        'stop_time': stop_time,
        'reused': False,
    }


# ---------------------------------------------------------------------------
# 心跳（redis-only，零 DB 写）
# ---------------------------------------------------------------------------

def heartbeat(user, session_id, now=None):
    now = now or _now()

    session = FrpSessionRecord.objects.filter(
        user=user, status='active', session_id=session_id).first()
    if not session:
        raise ValueError('会话不存在或已结束，请重新开始')

    if now >= session.stop_time:
        settle_session(session, FrpSessionRecord.EndReason.BALANCE_EXHAUSTED, now)
        tb, _ = UserTimeBalance.objects.get_or_create(user=user)
        return {'closed': True, 'balance_seconds': tb.balance_seconds}

    # 只写 redis，不写 DB
    _write_redis_session(
        user.uid, session.session_id, session.start_ts,
        session.stop_time, now)

    tb, _ = UserTimeBalance.objects.get_or_create(user=user)
    return {
        'closed': False,
        'balance_seconds': tb.balance_seconds,
        'stop_time': session.stop_time,
    }



# 会话结算

def settle_session(session, end_reason, end_ts=None):
    end_ts = end_ts or _now()
    used = max(0, int((end_ts - session.start_ts).total_seconds()))
    refund = max(0, int((session.stop_time - end_ts).total_seconds())) \
        if session.stop_time > end_ts else 0

    updated = FrpSessionRecord.objects.filter(
        session_id=session.session_id, status='active'
    ).update(
        status='closed',
        end_ts=end_ts,
        end_reason=end_reason,
        used_seconds=used,
        refund_seconds=refund,
    )
    if updated == 0:
        return  # 已结算过

    user = session.user
    with transaction.atomic():
        tb, _ = UserTimeBalance.objects.select_for_update().get_or_create(
            user=user, defaults={'enable': True})
        old_version = tb.version
        if used > 0:
            updated = UserTimeBalance.objects.filter(
                user=user, version=old_version
            ).update(
                balance_seconds=models.F('balance_seconds') - used,
                version=old_version + 1,
            )
            if updated == 0:
                raise DatabaseError('version校验失败,请重试')
            tb.refresh_from_db()

            TimeChangeRecord.objects.create(
                user=user,
                session_id=session.session_id,
                direction=TimeChangeRecord.Direction.DEDUCTION,
                amount_seconds=used,
                balance_after=max(0, tb.balance_seconds),
                scene=TimeChangeRecord.Scene.AUTO_SETTLE,
                detail_json={'end_reason': end_reason},
            )

        UserTimeBalance.objects.filter(user=user).update(
            is_online=False, current_session_id='')

    _clear_redis_session(user.uid)
    return used


def stop_session(user, session_id):
    session = FrpSessionRecord.objects.filter(
        user=user, status='active', session_id=session_id).first()
    if not session:
        raise ValueError('会话不存在或已结束')
    now = _now()
    used = settle_session(session, FrpSessionRecord.EndReason.MANUAL, now)
    tb, _ = UserTimeBalance.objects.get_or_create(user=user)
    return {'used_seconds': used or 0, 'balance_seconds': tb.balance_seconds}


# 巡检任务（供 management command 调用）

def settle_expired_sessions(now=None):
    # 巡检任务1：扫 stop_time 已过的 active 会话（余额耗尽自动断开）
    now = now or _now()
    sessions = FrpSessionRecord.objects.filter(status='active', stop_time__lte=now)
    count = 0
    for s in sessions:
        settle_session(s, FrpSessionRecord.EndReason.BALANCE_EXHAUSTED, s.stop_time)
        count += 1
    return count


def settle_timeout_sessions(now=None):

    # 巡检任务2：心跳超时掉线判定（redis-only，DB 零心跳写）。
    # 遍历 DB active 会话（量=在线数），逐个读 redis last_heartbeat：
    #   - 超过 SESSION_TTL 没心跳 -> 掉线，end_ts = last_hb + SESSION_TTL
    #   - redis 无 key（如被清）-> 保守按 start_ts+SESSION_TTL 兜底
    # 返回处理条数。

    now = now or _now()
    r = _redis()
    sessions = FrpSessionRecord.objects.filter(status='active')
    count = 0
    for s in sessions:
        data = r.hgetall(_session_key(s.user_id))
        if not data:
            # redis 无记录：可能是孤儿/被清，按最早可判掉线时间兜底
            end_ts = s.start_ts + timedelta(seconds=SESSION_TTL)
            if now >= end_ts:
                settle_session(s, FrpSessionRecord.EndReason.TIMEOUT_PATROL, end_ts)
                count += 1
            continue

        last_hb = _from_ts(int(data.get('last_heartbeat', 0)))
        if now - last_hb > timedelta(seconds=SESSION_TTL):
            end_ts = last_hb + timedelta(seconds=SESSION_TTL)
            settle_session(s, FrpSessionRecord.EndReason.TIMEOUT_PATROL, end_ts)
            count += 1
    return count
