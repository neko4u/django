import json
import time
import hashlib
import logging

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.conf import settings

from .decorators import frp_permission_required
from apps.login.models import UserInfo, FrpPermission
from . import utils
from . import services as frp_services
from .models import UserTimeBalance, FrpSessionRecord

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
    return JsonResponse({'code': 0, 'msg': 'success', **data})


def _json_err(msg, code=1, http=200):
    return JsonResponse({'code': code, 'msg': msg}, status=http)


# POST /api/frp_session/start — 开启会话（余额校验/幂等复用）
def api_frp_session_start(request):
    if request.method != 'POST':
        return _json_err('非法请求', http=405)
    user = _session_user(request)
    if not user:
        return _json_err('未登录或登录已过期', code=401, http=401)
    try:
        data = frp_services.start_session(user)
    except ValueError as e:
        return _json_err(str(e))
    return _json_ok(
        session_id=data['session_id'],
        balance_seconds=data['balance_seconds'],
        stop_time_ts=_ts(data['stop_time']),
        reused=data.get('reused', False),
    )


# POST /api/frp_session/heartbeat — 心跳（body: {"session_id": "xxx"}）
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
        data = frp_services.stop_session(user, session_id)
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
