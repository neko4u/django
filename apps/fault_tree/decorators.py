from functools import wraps
from django.http import JsonResponse
from .models import FaultTreePermission


def get_user_permission(request):
    """从 request 中获取当前用户的权限对象。未登录返回 None。"""
    uid = request.session.get('info', {}).get('uid')
    if not uid:
        return None
    return FaultTreePermission.objects.filter(user_id=uid, can_access=True).first()


def require_access(view_func):
    """要求用户有 can_access 权限（查看页面）"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == 'GET':
            # GET 请求：需要登录 + can_access
            perm = get_user_permission(request)
            if perm is None:
                return JsonResponse({'detail': '无访问权限'}, status=403)
        else:
            # POST/PUT/DELETE：需要登录 + can_edit
            perm = get_user_permission(request)
            if perm is None or not perm.can_edit:
                return JsonResponse({'detail': '无编辑权限'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


def require_edit(view_func):
    """要求用户有 can_edit 权限"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        perm = get_user_permission(request)
        if perm is None or not perm.can_edit:
            return JsonResponse({'detail': '无编辑权限'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


def check_permission(request):
    """检查并返回权限信息（供前端调用）"""
    uid = request.session.get('info', {}).get('uid')
    if not uid:
        return JsonResponse({'can_access': False, 'can_edit': False})
    perm = FaultTreePermission.objects.filter(user_id=uid).first()
    if not perm:
        return JsonResponse({'can_access': False, 'can_edit': False})
    return JsonResponse({
        'can_access': perm.can_access,
        'can_edit': perm.can_edit,
    })
