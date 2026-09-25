import json
import time
import hashlib
import logging
from datetime import datetime, timedelta, time as dt_time

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.conf import settings
from django.core.paginator import Paginator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .decorators import frp_permission_required
from apps.login.models import UserInfo, FrpPermission
from apps.common.http import client_ip
from . import utils
from . import services as frp_services
from .models import UserTimeBalance, FrpSessionRecord, FrpConnectionLog


logger = logging.getLogger(__name__)


@frp_permission_required()
def frp_index(request):
    config_data, config_err = utils.read_config()
    api_success, api_info = utils.get_frp_stats()
    context = {
        'page_title': 'FRP 服务管理',
        'config': config_data,
        'config_err': config_err,
        'api_info': api_info,
        'api_active': api_success,
        'perms': request.frp_perm,
    }
    return render(request, 'frpServer/frp_manage.html', context)


@frp_permission_required('can_start')
def api_frp_start(request):
    if request.method == "POST":
        success, msg = utils.start_service()
        return JsonResponse({'status': success, 'msg': msg})
    return JsonResponse({'status': False, 'msg': '非法请求'})


@frp_permission_required('can_stop')
def api_frp_stop(request):
    if request.method == "POST":
        success, msg = utils.stop_service()
        return JsonResponse({'status': success, 'msg': msg})
    return JsonResponse({'status': False, 'msg': '非法请求'})


@frp_permission_required('can_restart')
def api_frp_restart(request):
    if request.method == "POST":
        success, msg = utils.restart_service()
        return JsonResponse({'status': success, 'msg': msg})
    return JsonResponse({'status': False, 'msg': '非法请求'})


@frp_permission_required('can_get_new_token')
def api_frp_update_token(request):
    if request.method == "POST":
        success, result = utils.update_frp_token()
        if not success:
            return JsonResponse({'status': False, 'msg': result})
        utils.restart_service()
        return JsonResponse({'status': True, 'msg': f"Token已更新并重启: {result}"})
    return JsonResponse({'status': False, 'msg': '非法请求'})


@frp_permission_required()
def api_frp_status_json(request):
    api_success, api_info = utils.get_frp_stats()
    config_data, _ = utils.read_config()
    
    return JsonResponse({
        'active': api_success, 
        'data': api_info,
        'config_token': config_data.get('auth', {}).get('token', 'N/A') if config_data else 'N/A',
        'ts': time.time()
    })


@frp_permission_required()
def FrpToken(request):
    config_data, _ = utils.read_config()
    token = config_data.get('auth', {}).get('token', 'N/A')

    ts = int(time.time())

    sign_str = f"{token}:{ts}:{settings.SECRET_KEY}"
    sign = hashlib.sha256(sign_str.encode()).hexdigest()

    return JsonResponse({
        'isok': True,
        'config_token': token,
        'ts': ts,
        'sign': sign
    })


# fork: FRP 会话计费接口（FrpClient 调用）
# 鉴权：Authorization: Bearer <JWT>（复用 services.authenticate_user）

def _session_user(request):
    uid = frp_services.authenticate_user(request)
    if not uid:
        return None
    try:
        return UserInfo.objects.get(uid=uid)
    except UserInfo.DoesNotExist:
        return None


def _ts(dt):
    return int(dt.timestamp())


def _json_ok(**data):
    return JsonResponse({'code': 0, 'msg': 'success', 'server_time': int(time.time()), **data})


def _json_err(msg, code=1, http=200):
    return JsonResponse({'code': code, 'msg': msg}, status=http)


# POST /api/frp_session/start — 开启会话（余额校验/幂等复用）
@csrf_exempt
def api_frp_session_start(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    try:
        data = frp_services.start_session(user, client_ip=client_ip(request))
    except ValueError as e:
        return _json_err(str(e))

    return _json_ok(
        session_id=data['session_id'],
        balance_seconds=data['balance_seconds'],
        stop_time_ts=_ts(data['stop_time']),
        reused=data.get('reused', False),
    )


# POST /api/frp_session/heartbeat — 心跳（body: {"session_id": "xxx"}）
@csrf_exempt
def api_frp_session_heartbeat(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _json_err('请求体不是合法 JSON')
    session_id = body.get('session_id', '')
    if not session_id:
        return _json_err('缺少 session_id')
    try:
        data = frp_services.heartbeat(user, session_id)
    except ValueError as e:
        return _json_err(str(e))
    return _json_ok(
        closed=data['closed'],
        balance_seconds=data['balance_seconds'],
        stop_time_ts=_ts(data['stop_time']) if not data['closed'] else 0,
    )


# POST /api/frp_session/stop — 手动停止并结算（body: {"session_id": "xxx"}）
@csrf_exempt
def api_frp_session_stop(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    try:
        body = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return _json_err('请求体不是合法 JSON')
    session_id = body.get('session_id', '')
    if not session_id:
        return _json_err('缺少 session_id')
    try:
        data = frp_services.stop_session(user, session_id, client_ip=client_ip(request))
    except ValueError as e:
        return _json_err(str(e))

    return _json_ok(
        used_seconds=data['used_seconds'],
        balance_seconds=data['balance_seconds'],
    )


# GET /api/frp_session/status — 查询当前会话与余额（客户端启动同步）
def api_frp_session_status(request):
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)

    tb, _ = UserTimeBalance.objects.get_or_create(user=user)
    session = FrpSessionRecord.objects.filter(
        user=user, status='active').order_by('-start_ts').first()

    return _json_ok(
        has_session=bool(session),
        session_id=session.session_id if session else '',
        balance_seconds=tb.balance_seconds,
        stop_time_ts=_ts(session.stop_time) if session else 0,
        start_ts=_ts(session.start_ts) if session else 0,
    )





# fork: 远程端口租赁接口（FrpClient 调用）
#   分配时点: 客户端点「连接」时 allocate; 断开时 release

FRP_PUBLIC_HOST = "connections.sorielflow.com"   # 对外展示的访问域名(客户端拼接 host:port)


# POST /api/frp_port/allocate/ — 分配一个远程端口（需先开启时长）
@csrf_exempt
def api_frp_port_allocate(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)

    # 服务端复检门禁: 必须有活跃会话才允许占用端口
    if not FrpSessionRecord.objects.filter(user=user, status='active').exists():
        return _json_err('请先开启时长', code=2)

    try:
        port = frp_services.allocate_remote_port(user)
    except ValueError as e:
        return _json_err(str(e))
    return _json_ok(remote_port=port, host=FRP_PUBLIC_HOST)


# POST /api/frp_port/release/ — 释放当前端口租约（断开连接时调用）
@csrf_exempt
def api_frp_port_release(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    port = frp_services.release_remote_port(user.uid)
    return _json_ok(remote_port=port or 0)


# GET /api/frp_port/ — 查询当前端口（客户端重启后恢复显示用）
def api_frp_port_current(request):
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    port = frp_services.get_remote_port(user.uid)
    return _json_ok(remote_port=port or 0, host=FRP_PUBLIC_HOST)


# GET /api/user_profile/ — 当前用户资料(客户端取头像用, JWT 鉴权)
@csrf_exempt
def api_user_profile(request):
    if request.method != 'GET':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    avatar = user.avatar.url if user.avatar else ''
    return _json_ok(
        uid=user.uid,
        name=user.name,
        avatar=avatar,                 # 相对路径, 形如 /media/avatars/10001.png
    )




# ---------------------------------------------------------------------------
# 历史连接：连接事件流水查询
#   GET /api/frp_connection_log/
#     ?preset=today|yesterday|last3|last7   可选，缺省 last7
#     ?start=YYYY-MM-DD&end=YYYY-MM-DD      可选，给了就以它为准（优先于 preset）
#     ?page=1&page_size=20                  page_size 只接受 20/50/100
# ---------------------------------------------------------------------------

CONNECTION_LOG_PAGE_SIZES = (20, 50, 100)
CONNECTION_LOG_MAX_DAYS = 366


def _parse_ymd(value):
    """'YYYY-MM-DD' -> date；失败返回 None"""
    try:
        return datetime.strptime((value or '').strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _resolve_log_range(request):
    """解析查询区间，返回 (start_date, end_date, error_msg)

    优先级：显式 start/end  >  preset  >  默认近 7 天
    服务器 TIME_ZONE = Asia/Shanghai 且 USE_TZ = False，所以这里的本地日期即中国日期。
    """
    today = timezone.now().date()

    raw_start = (request.GET.get('start') or '').strip()
    raw_end = (request.GET.get('end') or '').strip()

    if raw_start or raw_end:
        start = _parse_ymd(raw_start)
        end = _parse_ymd(raw_end)
        if not start or not end:
            return None, None, '日期格式不正确，应为 YYYY-MM-DD'
        if start > end:
            start, end = end, start
        if (end - start).days + 1 > CONNECTION_LOG_MAX_DAYS:
            return None, None, f'查询区间不能超过 {CONNECTION_LOG_MAX_DAYS} 天'
        return start, end, None

    preset = (request.GET.get('preset') or 'last7').strip().lower()
    if preset == 'today':
        return today, today, None
    if preset == 'yesterday':
        d = today - timedelta(days=1)
        return d, d, None
    if preset == 'last3':
        return today - timedelta(days=2), today, None
    # 默认 / last7
    return today - timedelta(days=6), today, None


def api_frp_connection_logs(request):
    """历史连接列表（只返回当前用户自己的记录）"""
    if request.method != 'GET':
        return _json_err('非法请求', http=405)

    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)

    start_date, end_date, err = _resolve_log_range(request)
    if err:
        return _json_err(err)

    # ---- 分页参数（白名单，防 page_size=99999 拖库）----
    try:
        page = int(request.GET.get('page') or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    try:
        page_size = int(request.GET.get('page_size') or CONNECTION_LOG_PAGE_SIZES[0])
    except (TypeError, ValueError):
        page_size = CONNECTION_LOG_PAGE_SIZES[0]
    if page_size not in CONNECTION_LOG_PAGE_SIZES:
        page_size = CONNECTION_LOG_PAGE_SIZES[0]

    # ---- 区间用 datetime 边界（而不是 __date），才能吃到 (user, event_ts) 索引 ----
    start_dt = datetime.combine(start_date, dt_time.min)
    end_dt = datetime.combine(end_date, dt_time.max)

    qs = (FrpConnectionLog.objects
          .filter(user=user, event_ts__gte=start_dt, event_ts__lte=end_dt)
          .order_by('-event_ts'))

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)      # 页码非法/越界会自动纠正

    items = []
    for row in page_obj.object_list:
        items.append({
            'session_id': row.session_id,
            'type': row.event_type,                        # CONNECT / REUSE / DISCONNECT
            'type_text': row.get_event_type_display(),     # 连接 / 重新连接 / 断开
            'ts': row.event_ts.strftime('%Y-%m-%d %H:%M:%S'),
            'ts_ts': _ts(row.event_ts),
            'ip': row.client_ip or '',                     # 无请求来源的事件为空
            'reason': row.reason,
            'reason_text': row.get_reason_display(),       # 备注
            'duration_seconds': row.duration_seconds,      # 仅断开事件有值
        })

    return _json_ok(
        items=items,
        total=paginator.count,
        page=page_obj.number,
        page_size=page_size,
        pages=paginator.num_pages,
        has_next=page_obj.has_next(),
        has_prev=page_obj.has_previous(),
        range={
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
        },
    )

