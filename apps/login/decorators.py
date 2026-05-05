# login/decorators.py

from django.shortcuts import redirect
from django.http import JsonResponse
from functools import wraps

def login_required_view(view_func):
    """
    用于普通视图函数的登录检查装饰器。
    如果用户未登录，则重定向到登录页面。
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def login_required_api(view_func):
    """
    用于API（返回JsonResponse）视图的登录检查装饰器。
    如果用户未登录，则返回JSON格式的401 Unauthorized错误。
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return JsonResponse({'status': 'error', 'message': '用户未登录'}, status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def admin_login_required_api(view_func):
    return 1