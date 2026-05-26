from functools import wraps
from django.http import JsonResponse
from .services import authenticate_user, check_frp_permission

def frp_permission_required(perm_name='can_access'):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user_id = authenticate_user(request)
            if not user_id:
                return JsonResponse({'isok': False, 'msg': '未登录'}, status=401)

            ok, result = check_frp_permission(user_id, perm_name)
            if not ok:
                return JsonResponse({'isok': False, 'msg': result}, status=403)

            request.frp_perm = result
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
