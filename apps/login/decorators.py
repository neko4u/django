# login/decorators.py

from django.shortcuts import redirect
from django.http import JsonResponse
from functools import wraps

# 会话失效后回哪个登录页
FRP_LOGIN = 'flogin'
NORMAL_LOGIN = 'flogin'


def login_url_for(request, to=None):
    """决定 session 失效后跳回哪个登录页。

    优先级：
      1) 显式指定（装饰器里的 to='flogin' / 'login'，或函数直接传）
      2) 请求里带 from=frp 标记（frp 页面内嵌的表单会带上它）
      3) 兜底 -> 通用登录页
    """
    if to:
        return to
    if (request.POST.get('from') or request.GET.get('from')) == 'frp':
        return FRP_LOGIN
    return NORMAL_LOGIN


def login_required_view(view_func=None, *, to=None):
    """页面类登录校验。

    两种用法都支持（老代码不用动）：
        @login_required_view                  # 失效后回通用登录页 /login/
        @login_required_view(to='flogin')     # 失效后回 frp 登录页 /flogin/
    """
    def decorator(func):
        @wraps(func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.session.get('is_logged_in'):
                return redirect(login_url_for(request, to))
            return func(request, *args, **kwargs)
        return _wrapped_view

    if view_func is not None:       # 裸用法: @login_required_view
        return decorator(view_func)
    return decorator                # 带参用法: @login_required_view(to=...)


def login_required_api(view_func):
    # 用于API（返回JsonResponse）视图的登录检查装饰器。
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return JsonResponse({'status': 'error', 'message': '用户未登录'}, status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped_view
