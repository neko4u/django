from django.shortcuts import render, redirect
from django.http import JsonResponse
from .decorators import frp_permission_required
from apps.login.models import UserInfo, FrpPermission
from . import utils
import time
import hashlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


@frp_permission_required()
def frp_index(request):
    """FRP 管理主页：初始载入"""
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
    """提供给前端 Ajax 定时刷新的接口"""
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
