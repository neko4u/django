# apps/suadmin/decorators.py

from functools import wraps

from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect

from .models import SuadminAdmin


def get_admin(request):
    """取当前会话对应的管理员记录；登录了但不是管理员 / 已停用 -> None。"""
    if not request.session.get('is_logged_in'):
        return None
    uid = (request.session.get('info') or {}).get('uid')
    if uid is None:
        return None
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    return SuadminAdmin.objects.filter(uid_id=uid, enable=True).first()


def is_admin(request):
    """是不是「启用状态的管理员」。"""
    return get_admin(request) is not None


def has_perm(request, code):
    """是否有某个权限码。"""
    admin = get_admin(request)
    return bool(admin and admin.has_perm(code))


# ============================ 页面类视图 ============================

def admin_required(view_func):
    """只要求是启用状态的管理员（用于后台首页、导航等通用页面）。"""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return redirect('login')
        if get_admin(request) is None:
            return HttpResponseForbidden('无权限访问')
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_perm(code):
    """要求是启用状态的管理员，且有指定权限码（用于具体功能页）。"""
    def deco(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.session.get('is_logged_in'):
                return redirect('login')
            admin = get_admin(request)
            if admin is None or not admin.has_perm(code):
                return HttpResponseForbidden('无权限访问')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return deco


# ============================ 接口类视图（返回 JSON） ============================

def admin_required_api(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return JsonResponse({'status': 'error', 'message': '用户未登录'}, status=401)
        if get_admin(request) is None:
            return JsonResponse({'status': 'error', 'message': '无权限'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_perm_api(code):
    def deco(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.session.get('is_logged_in'):
                return JsonResponse({'status': 'error', 'message': '用户未登录'}, status=401)
            admin = get_admin(request)
            if admin is None or not admin.has_perm(code):
                return JsonResponse({'status': 'error', 'message': '无权限'}, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return deco
