from apps.login.models import FrpPermission
from apps.login.services import JwtService

import json
import logging
import time
import uuid
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import transaction, models
from django.db.utils import DatabaseError
from django.utils import timezone

from .models import UserTimeBalance, TimeChangeRecord, FrpSessionRecord, FrpConnectionLog
import requests

logger = logging.getLogger(__name__)


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

SESSION_TTL = 120            # 心跳超时阈值（秒），超过判掉线
HEARTBEAT_INTERVAL = 30      # 客户端心跳周期（秒），仅供参考/校验
REDIS_SESSION_EXPIRE = 86400  # redis 会话 key 兜底 TTL（24h），孤儿 key 由巡检清理


# 会话结束原因 -> 连接事件流水的「备注」
_DISCONNECT_REASON_MAP = {
    FrpSessionRecord.EndReason.MANUAL: FrpConnectionLog.Reason.MANUAL,
    FrpSessionRecord.EndReason.BALANCE_EXHAUSTED: FrpConnectionLog.Reason.BALANCE_EXHAUSTED,
    FrpSessionRecord.EndReason.TIMEOUT_PATROL: FrpConnectionLog.Reason.TIMEOUT_PATROL,
    FrpSessionRecord.EndReason.FORCED: FrpConnectionLog.Reason.FORCED,
}


def _log_connection_event(user, session_id, event_type, event_ts, reason,
                          client_ip=None, duration_seconds=0, detail=None):
    try:
        FrpConnectionLog.objects.create(
            user=user,
            session_id=session_id or '',
            event_type=event_type,
            event_ts=event_ts,
            client_ip=(client_ip or None),
            reason=reason,
            duration_seconds=duration_seconds or 0,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    except Exception as exc:
        logger.error(
            f'写连接事件流水失败 uid={getattr(user, "uid", None)} '
            f'session={session_id} type={event_type}: {exc}'
        )


def _redis():
    return cache.client.get_client()


def _session_key(uid):
    return f'frp:session:{uid}'


def _hgetall_str(key):
    raw = _redis().hgetall(key) or {}
    out = {}
    for k, v in raw.items():
        kk = k.decode() if isinstance(k, bytes) else str(k)
        vv = v.decode() if isinstance(v, bytes) else str(v)
        out[kk] = vv
    return out



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
    pipe.hmset(key, {
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
def extend_active_session(user, seconds):
    """把当前 active 会话的到期时间顺延 N 秒（连接中充值/加时长时调用）。

    设计要点：
      - 用 F() 表达式做原子自增，避免「读-改-写」在并发下丢更新；
      - 只取最新的一条 active 会话（按 start_ts 倒序）；
      - 同步 Redis 的 stop_time（心跳会用 DB 值重写 redis，这里同步只为让
        下一次心跳到来前显示也一致）；
      - 返回 True/False：没有 active 会话时返回 False（只加余额，不需要续命）。

    ⚠️ 顺延只延长「当前会话」，不产生任何时长增减 ——
       余额在充值/兑换时已经加过了，所以这里**不写 TimeChangeRecord**，避免重复记账。
    """
    if seconds <= 0:
        return False

    session = (
        FrpSessionRecord.objects
        .filter(user=user, status='active')
        .order_by('-start_ts')
        .first()
    )
    if not session:
        return False

    FrpSessionRecord.objects.filter(
        session_id=session.session_id, status='active'
    ).update(stop_time=models.F('stop_time') + timedelta(seconds=seconds))

    session.refresh_from_db(fields=['stop_time'])

    try:
        r = _redis()
        key = _session_key(user.uid)
        if r.exists(key):
            r.hset(key, 'stop_time', _to_ts(session.stop_time))
            r.expire(key, REDIS_SESSION_EXPIRE)
    except Exception as exc:
        logger.error(f'顺延会话时同步 Redis 失败 uid={user.uid}: {exc}')

    logger.info(
        f'用户 {user.uid} 会话顺延 {seconds}s，'
        f'新到期时间 {session.stop_time}，session={session.session_id}'
    )
    return True




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
            extend_active_session(user, seconds)


    return tb.balance_seconds


# 会话开始

def start_session(user, now=None, client_ip=None):
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

        _log_connection_event(
            user=user,
            session_id=existing.session_id,
            event_type=FrpConnectionLog.EventType.REUSE,
            event_ts=now,
            reason=FrpConnectionLog.Reason.SESSION_REUSE,
            client_ip=client_ip,
            detail={
                'session_start_ts': _to_ts(existing.start_ts),
                'session_stop_time': _to_ts(existing.stop_time),
                'balance_seconds': tb.balance_seconds,
            },
        )

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

        # 事件流水：新建会话（主动连接）
        # 放在 atomic 内，事务回滚时本事件一并回滚，保证与主记录一致
        _log_connection_event(
            user=user,
            session_id=session_id,
            event_type=FrpConnectionLog.EventType.CONNECT,
            event_ts=start_ts,
            reason=FrpConnectionLog.Reason.ACTIVE_CONNECT,
            client_ip=client_ip,
            detail={
                'start_ts': _to_ts(start_ts),
                'stop_time': _to_ts(stop_time),
                'balance_seconds': tb.balance_seconds,
            },
        )


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
        # DB 已无该会话 -> 清理可能残留的 redis 痕迹
        # 仅当残留记录的 session_id 与本次请求一致时才清, 避免误删同 uid 其他设备的新会话
        try:
            r0 = _redis()
            cur = r0.hget(_session_key(user.uid), 'session_id')
            if cur is not None:
                cur = cur.decode() if isinstance(cur, bytes) else cur
                if cur == session_id:
                    _clear_redis_session(user.uid)
        except Exception:
            pass
        raise ValueError('会话已失效，请重新开启时长')


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

def settle_session(session, end_reason, end_ts=None, client_ip=None):
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

    # 事件流水：断开。
    # 只有「主动断开」（有用户请求）才记 IP；时长耗尽/心跳超时是系统侧触发，没有请求 → 留空。
    # 位置在 updated == 0 的幂等 return 之后，天然不会重复写。
    _log_connection_event(
        user=user,
        session_id=session.session_id,
        event_type=FrpConnectionLog.EventType.DISCONNECT,
        event_ts=end_ts,
        reason=_DISCONNECT_REASON_MAP.get(end_reason, FrpConnectionLog.Reason.OTHER),
        client_ip=client_ip if end_reason == FrpSessionRecord.EndReason.MANUAL else None,
        duration_seconds=used,
        detail={'refund_seconds': refund},
    )

    return used



def stop_session(user, session_id, client_ip=None):
    session = FrpSessionRecord.objects.filter(
        user=user, status='active', session_id=session_id).first()
    if not session:
        raise ValueError('会话不存在或已结束')
    now = _now()
    used = settle_session(session, FrpSessionRecord.EndReason.MANUAL, now,
                          client_ip=client_ip)
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
        data = _hgetall_str(_session_key(s.user_id))

        # 最后心跳时间戳（缺失/非法一律按 start_ts 兜底，绝不能回落成 0/1970）
        raw_hb = data.get('last_heartbeat')
        last_hb_ts = int(raw_hb) if raw_hb and raw_hb.isdigit() else None

        if last_hb_ts is None:
            # redis 无记录或字段缺失：按最早可判掉线时间兜底
            end_ts = s.start_ts + timedelta(seconds=SESSION_TTL)
            if now >= end_ts:
                settle_session(s, FrpSessionRecord.EndReason.TIMEOUT_PATROL, end_ts)
                count += 1
            continue

        last_hb = _from_ts(last_hb_ts)
        if now - last_hb > timedelta(seconds=SESSION_TTL):
            end_ts = last_hb + timedelta(seconds=SESSION_TTL)
            settle_session(s, FrpSessionRecord.EndReason.TIMEOUT_PATROL, end_ts)
            count += 1
    return count




# ---------------------------------------------------------------------------
# 巡检任务3/4：对账防伪 + 黑名单管理（调 frps fork 本地管理 API）
# ---------------------------------------------------------------------------

FRPS_API = "http://127.0.0.1:7500"          # frps 管理端口（同机）
BAN_TIERS = [60, 300, 1800]                  # 递增拉黑档位：1m / 5m / 30m（封顶）


def _frps_get(path, timeout=3):
    return requests.get(FRPS_API + path, timeout=timeout).json()


def _frps_post(path, timeout=3):
    return requests.post(FRPS_API + path, timeout=timeout).json()


def get_frps_online_uids():
    """拉取 frps 当前所有在线 uid（字符串列表）"""
    data = _frps_get('/api/uid_connections')
    return [str(item.get('uid')) for item in (data.get('data') or [])]


def get_frps_blacklist():
    """拉取 frps 黑名单 uid（字符串列表）"""
    data = _frps_get('/api/uid_blacklist')
    return [str(x) for x in (data.get('data') or [])]


def reconcile_rogue_connections():
    # 巡检任务3：对账防伪。
    # frps 在线 但 redis 无该 uid -> 伪造/未授权连接：
    #   ① 调 frps close 断开连接
    #   ② 递增拉黑（违规计数 -> 档位 1m/5m/30m 封顶）
    # 返回处理条数。
    r = _redis()
    try:
        frps_uids = set(get_frps_online_uids())
    except Exception:
        return 0  # frps 不可达，跳过本轮

    redis_uids = {str(u).decode() if isinstance(u, bytes) else str(u)
                  for u in r.smembers('frp:online_uids')}

    rogue = frps_uids - redis_uids
    for uid in rogue:
        #   曾有过会话记录的 uid(可能只是心跳抖动被任务2结算) -> 只断不拉黑
        #   从未有过任何会话记录的 uid(纯伪造/扫描)          -> 断开 + 递增拉黑
        had_session = False
        try:
            had_session = FrpSessionRecord.objects.filter(user_id=uid).exists()
        except Exception:
            had_session = False

        # 断开 frps 连接(两种情况都要断: 没有有效会话就不该占用 frps)
        try:
            reason = 'session_expired' if had_session else 'unauthorized'
            _frps_post(f'/api/uid_connection/{uid}/close?reason={reason}')
        except Exception:
            pass

        # 有会话痕迹 -> 不拉黑
        if had_session:
            continue

        # 纯伪造连接 -> 递增拉黑（redis 计数决定档位）
        vkey = f'frp:violation:{uid}'
        count = r.incr(vkey)
        r.expire(vkey, 30 * 24 * 3600)  # 计数保留 30 天
        tier = min(count - 1, len(BAN_TIERS) - 1)
        ban_sec = BAN_TIERS[tier]
        try:
            _frps_post(f'/api/uid_blacklist/add?uid={uid}')
            r.setex(f'frp:ban_until:{uid}', ban_sec, str(ban_sec))
        except Exception:
            pass
    return len(rogue)



def release_expired_bans():
    # 巡检任务4：黑名单到期自动解除。
    # 对比 frps 黑名单 与 redis 到期标记，已过期的调 remove 解除。
    # 返回解除条数。
    r = _redis()
    try:
        banned = get_frps_blacklist()
    except Exception:
        return 0

    released = 0
    for uid in banned:
        # 有到期标记 -> 还没到期；无标记(过期被删/直接 add 的) -> 视为到期
        if not r.exists(f'frp:ban_until:{uid}'):
            try:
                _frps_post(f'/api/uid_blacklist/remove?uid={uid}')
                released += 1
            except Exception:
                pass
    return released


# 巡检任务5：会话层孤儿清理（redis 与 DB 不一致时, 一律以 DB 为准）
# 防止抖动导致正常用户被误认为非法用户拉黑

def cleanup_orphan_sessions():
    """
    扫描 redis 里的会话痕迹, 与 DB active 会话比对:
      - redis 有痕迹但 DB 无该 uid 的 active 会话 -> 清理(脏数据)
      - DB 有 active 但 redis 无 key -> 不动(由任务2 按 start_ts+TTL 兜底结算)
    返回清理条数。
    """
    r = _redis()

    active_uids = {
        str(uid) for uid in FrpSessionRecord.objects.filter(status='active')
        .values_list('user_id', flat=True)
    }

    cleaned = 0

    # 1) 在线集合中的脏 uid
    for member in r.smembers('frp:online_uids'):
        uid = member.decode() if isinstance(member, bytes) else str(member)
        if uid not in active_uids:
            _clear_redis_session(uid)
            cleaned += 1

    # 2) 残留的会话 hash（可能已不在在线集合里）
    for key in r.scan_iter(match='frp:session:*', count=100):
        k = key.decode() if isinstance(key, bytes) else str(key)
        uid = k.rsplit(':', 1)[-1]
        if uid not in active_uids:
            r.delete(k)
            r.srem('frp:online_uids', uid)
            cleaned += 1

    return cleaned




# 端口租赁：远程端口由服务器在 [PORT_MIN, PORT_MAX] 内随机分配
#   frp:ports_free     SET    空闲端口池（分配=SPOP 原子弹出，释放=SADD 归还）
#   frp:ports_owner    HASH   port -> "uid|分配时间戳"
#   frp:port_of:{uid}  STRING 该 uid 当前租到的端口（幂等：重复分配返回同一个）
# 并发安全由 Lua 脚本保证（EVAL 原子执行），不会出现两个请求拿到同一端口。



PORT_MIN = 6100
PORT_MAX = 6500
PORT_LEASE_GRACE = 120   # 秒：分配后 N 秒内即使 frps 未上线也不回收（等客户端连上）


def _port_of_key(uid):
    return f'frp:port_of:{uid}'


def _dec(v):
    if v is None:
        return None
    return v.decode() if isinstance(v, bytes) else str(v)


_ALLOC_PORT_LUA = """
redis.replicate_commands()
local exist = redis.call('GET', KEYS[3])
if exist then return exist end
local port = redis.call('SPOP', KEYS[1])
if not port then return false end
redis.call('HSET', KEYS[2], port, ARGV[1] .. '|' .. ARGV[2])
redis.call('SET', KEYS[3], port)
return port
"""

_RELEASE_PORT_LUA = """
local port = redis.call('GET', KEYS[3])
if not port then return false end
local owner = redis.call('HGET', KEYS[2], port)
if owner then
  local uid = string.match(owner, '^[^|]+')
  if uid ~= ARGV[1] then return false end
end
redis.call('DEL', KEYS[3])
redis.call('HDEL', KEYS[2], port)
redis.call('SADD', KEYS[1], port)
return port
"""


def ensure_port_pool():
    """首次使用时初始化空闲端口池（已有归属的端口不放入池）。"""
    r = _redis()
    if not r.set('frp:ports_seeded', '1', nx=True):
        return
    pipe = r.pipeline()
    for p in range(PORT_MIN, PORT_MAX + 1):
        pipe.sadd('frp:ports_free', p)
    pipe.execute()
    for port in (r.hgetall('frp:ports_owner') or {}):
        r.srem('frp:ports_free', port)


def allocate_remote_port(user):
    """为 uid 分配一个空闲端口（幂等：已有租约直接返回）。池满抛 ValueError。"""
    ensure_port_pool()
    r = _redis()
    res = r.eval(
        _ALLOC_PORT_LUA, 3,
        'frp:ports_free', 'frp:ports_owner', _port_of_key(user.uid),
        str(user.uid), str(int(time.time())))
    if res is None or res is False:
        raise ValueError('端口池已满，请稍后重试')
    return int(_dec(res))


def get_remote_port(uid):
    """查询 uid 当前租到的端口（无则 None）。"""
    v = _dec(_redis().get(_port_of_key(uid)))
    return int(v) if v else None


def release_remote_port(uid):
    """释放 uid 的端口租约（幂等）。返回被释放的端口或 None。"""
    r = _redis()
    res = r.eval(
        _RELEASE_PORT_LUA, 3,
        'frp:ports_free', 'frp:ports_owner', _port_of_key(uid),
        str(uid))
    return int(_dec(res)) if res else None


def port_pool_stats():
    """端口池统计（供巡检/排查用）。"""
    ensure_port_pool()
    r = _redis()
    return {

        'free': r.scard('frp:ports_free'),
        'used': r.hlen('frp:ports_owner'),
        'total': PORT_MAX - PORT_MIN + 1,
    }


def rebuild_port_pool():
    """自愈：按 owner 记录重建空闲池（free = 全区间 - 已租出）。返回已租出数量。"""
    r = _redis()
    owned = {_dec(p) for p in (r.hgetall('frp:ports_owner') or {})}
    pipe = r.pipeline()
    for p in range(PORT_MIN, PORT_MAX + 1):
        if str(p) in owned:
            pipe.srem('frp:ports_free', p)
        else:
            pipe.sadd('frp:ports_free', p)
    pipe.execute()
    r.set('frp:ports_seeded', '1')
    return len(owned)


def cleanup_orphan_port_leases(now=None):
    """
    巡检：回收孤儿端口租约（客户端崩溃/异常退出的兜底）。
    判定：该 uid 已不在 frps 在线列表，且租约已超过 PORT_LEASE_GRACE 秒 -> 释放。
          （宽限期用于等待客户端把隧道真正连起来）
    返回回收条数。
    """
    now = now or _now()
    r = _redis()
    try:
        frps_uids = set(get_frps_online_uids())
    except Exception:
        return 0

    rebuild_port_pool()   # 顺手自愈一次，保证 free 池与 owner 不矛盾

    owners = r.hgetall('frp:ports_owner') or {}
    now_ts = int(now.timestamp())
    cleaned = 0
    for p, val in owners.items():
        port = int(_dec(p))
        uid, _, ts = _dec(val).partition('|')
        if uid in frps_uids:
            continue                      # 连接还在, 保留
        try:
            if now_ts - int(ts or 0) < PORT_LEASE_GRACE:
                continue                  # 宽限期内, 等客户端连上
        except ValueError:
            pass
        r.delete(_port_of_key(uid))
        r.hdel('frp:ports_owner', port)
        r.sadd('frp:ports_free', port)
        cleaned += 1
    return cleaned

