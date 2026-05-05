from django.shortcuts import render, redirect
from django.http import JsonResponse
from functools import wraps
from apps.login.models import UserInfo, FrpPermission
from . import utils
import time
import hashlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


# --- 权限装饰器保持不变 ---
# def frp_permission_required(perm_name='can_access'):
#     def decorator(view_func):
#         @wraps(view_func)
#         def _wrapped_view(request, *args, **kwargs):
#             if not request.session.get('is_logged_in'):
#                 return redirect('login')
#             user_info = request.session.get('info', {})
#             user_id = user_info.get('uid') or user_info.get('id')
#             if not user_id:
#                 return redirect('login')
#             try:
#                 perm = FrpPermission.objects.get(user_id=user_id)
#                 if not perm.can_access:
#                     return render(request, 'login/403.html', {'error': '无FRP权限'})
#                 if perm_name and not getattr(perm, perm_name, False):
#                     if request.headers.get('x-requested-with') == 'XMLHttpRequest':
#                         return JsonResponse({'status': False, 'msg': '权限不足'})
#                     return render(request, 'login/403.html', {'error': f'权限不足: {perm_name}'})
#                 request.frp_perm = perm
#             except FrpPermission.DoesNotExist:
#                 return render(request, 'login/403.html', {'error': '尚未配置FRP权限'})
#             return view_func(request, *args, **kwargs)
#         return _wrapped_view
#     return decorator



# 兼容了token
def frp_permission_required(perm_name='can_access'):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user_id = None
            # ===== session 登录 =====
            if request.session.get('is_logged_in'):
                user_info = request.session.get('info', {})
                user_id = user_info.get('uid') or user_info.get('id')
            # ===== token 登录 =====
            if not user_id:
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header[7:]
                    try:
                        from apps.login.services import JwtService
                        payload = JwtService.verify_token(token)
                    except Exception as e:
                        return JsonResponse({
                            'isok': False,
                            'msg': f'JWT异常: {str(e)}'
                        }, status=500)
                    if payload:
                        user_id = payload.get('user_id') or payload.get('uid') or payload.get('id')
                    else:
            if not user_id:
                return JsonResponse({'isok': False, 'msg': '未登录'}, status=401)
            try:
                perm = FrpPermission.objects.get(user_id=user_id)

                if not perm.can_access:
                    return JsonResponse({'isok': False, 'msg': '无FRP权限'}, status=403)

                if perm_name and not getattr(perm, perm_name, False):
                    return JsonResponse({'isok': False, 'msg': '权限不足'}, status=403)

                request.frp_perm = perm

            except FrpPermission.DoesNotExist:
                return JsonResponse({'isok': False, 'msg': '未配置权限'}, status=403)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator

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

# 启动、停止、重启、Token更新函数保持 utils 调用逻辑不变...
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
        if not success: return JsonResponse({'status': False, 'msg': result})
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

# 提供查询秘钥的接口
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

