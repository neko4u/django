from functools import wraps
from django.http import JsonResponse
from .models import UserPermission

def require_permission(perm_name):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            uid = request.session['info']['uid']
            if not uid:
                return JsonResponse({'error': '未登录'}, status=401)
            try:
                perm = UserPermission.objects.get(uid=uid)
            except UserPermission.DoesNotExist:
                return JsonResponse({'error': '无权限'}, status=403)
            if not getattr(perm, perm_name, False):
                return JsonResponse({'error': '无权限'}, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

def superadmin_required_api(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        uid = request.session['info']['uid']
        if not uid:
            return JsonResponse({'error': '未登录'}, status=401)
        try:
            perm = UserPermission.objects.get(uid=uid)
        except UserPermission.DoesNotExist:
            return JsonResponse({'error': '无权限'}, status=403)
        if not perm.is_superadmin:
            return JsonResponse({'error': '需要超级管理员权限'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped_view

require_chat_access = require_permission('can_access_chat')
require_set_temperature = require_permission('can_set_temperature')
require_set_top_p = require_permission('can_set_top_p')
require_set_presence_penalty = require_permission('can_set_presence_penalty')
require_set_frequency_penalty = require_permission('can_set_frequency_penalty')
require_set_max_tokens = require_permission('can_set_max_tokens')