from functools import wraps
from django.http import JsonResponse
from .services import authenticate_user, check_frp_permission

def frp_permission_required(perm_name='can_access'):
    """
    装饰器：要求用户已登录并拥有指定的 FRP 权限。
    支持 session 登录与 Bearer token 登录，统一进行权限校验。
    校验通过后，将权限对象挂载到 request.frp_perm 上。
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 第一步：提取用户 ID
            user_id = authenticate_user(request)
            if not user_id:
                return JsonResponse({'isok': False, 'msg': '未登录'}, status=401)

            # 第二步：检查权限
            ok, result = check_frp_permission(user_id, perm_name)
            if not ok:
                return JsonResponse({'isok': False, 'msg': result}, status=403)

            # 第三步：挂载权限对象并执行视图
            request.frp_perm = result
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
