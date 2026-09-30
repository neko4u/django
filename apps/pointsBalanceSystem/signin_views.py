# apps/pointsBalanceSystem/signin_views.py
"""签到接口（给 findex 页面的「获取积分 / 参与签到」卡片用）。

两个接口：

    GET  /points/api/sign-in/status/   查状态（当前活动 + 今天签没签 + 余额）
    POST /points/api/sign-in/          签到

安全约定（都是硬要求，别改）：

1. **uid 只从 session 取，绝不接受前端传参**。
   前端就算在 body 里塞 `uid=别人的id`，也完全不会被读取。

2. **不豁免 CSRF**。
   frpServer 里那些 `@csrf_exempt` 是给**桌面客户端**用的（它没有 cookie 会话）。
   签到是浏览器里发起、且要发积分的写操作，必须走 Django 标准 CSRF 校验。
   前端把 csrftoken 放在 `X-CSRFToken` 头里（页面里 `{% csrf_token %}` 会同时种下 cookie）。

3. **`ensure_csrf_cookie`**：status 接口主动种一次 csrftoken cookie，
   这样即使将来 findex 模板里不再有 `{% csrf_token %}`，第一次进来也能直接签到。

4. **不让异常细节泄漏给用户**：`execute()` 内部已经消化了数据库层错误，
   这里再兜一层，未预期的异常只记日志，返回统一的友好文案。

HTTP 状态码约定：

    200  业务结果（包括「今天已签过」「活动已结束」这类正常状态，看 body 里的 `code` 分支）
    400  参数不合法
    401  未登录 / 用户不存在
    405  方法不对
    500  服务端未预期异常
"""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.common.http import client_ip
from apps.login.decorators import login_required_api
from apps.login.models import UserInfo

from .signin_service import SignInService

logger = logging.getLogger(__name__)


def _session_user(request):
    """从 session 里取登录用户。

    ⚠️ 只认 session；返回值可能是 None（未登录 / 已注销），调用方必须判空。
    """
    uid = (request.session.get('info') or {}).get('uid')
    if not uid:
        return None
    return UserInfo.objects.filter(uid=uid, is_delete=False).first()


def _param(request, name):
    """取一个参数：POST 表单 / query 优先，其次 JSON body。"""
    ct = (request.content_type or '')
    if ct.startswith('application/json'):
        try:
            body = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(body, dict):
            return None
        val = body.get(name)
        return None if val is None else str(val)
    val = request.POST.get(name)
    if val is None:
        val = request.GET.get(name)
    return val


def _err(code, message, http=200, **extra):
    payload = {'status': 'error', 'code': code, 'ok': False, 'message': message}
    payload.update(extra)
    return JsonResponse(payload, status=http)


# ---------------------------------------------------------------------------


@ensure_csrf_cookie
@login_required_api
def sign_in_status(request):
    """GET /points/api/sign-in/status/

    返回：
        {status, code, activity|null, signed_today, today_points,
         sign_time|null, sign_date, balance, account_enable}
    """
    if request.method != 'GET':
        return _err('METHOD_NOT_ALLOWED', '请求方法不对', http=405)

    user = _session_user(request)
    if user is None:
        return _err('USER_INVALID', '用户不存在或已注销，请重新登录', http=401)

    try:
        data = SignInService.today_status(user)
    except Exception:
        logger.exception('查询签到状态失败 uid=%s', getattr(user, 'uid', None))
        return _err('INTERNAL_ERROR', '系统繁忙，请稍后重试', http=500)

    payload = {'status': 'success', 'code': 'OK', 'ok': True, 'message': 'ok'}
    payload.update(data)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------


@login_required_api
def sign_in(request):
    """POST /points/api/sign-in/

    参数（都可选）：
        activity_id  指定要签的活动；不传则自动选当前进行中的一个

    返回：把 SignInService.execute() 的结果原样透出，外加 status 字段。
    前端请按 `code` 分支：
        SUCCESS              签到成功，已发积分
        ALREADY_SIGNED       今天已签过（正常状态，不是错误）
        NO_ACTIVITY          没有进行中的活动
        ACTIVITY_DISABLED / ACTIVITY_NOT_STARTED / ACTIVITY_ENDED
        ACCOUNT_DISABLED     积分账户已停用
        VERSION_CONFLICT     并发冲突，提示用户稍后重试
    """
    if request.method != 'POST':
        return _err('METHOD_NOT_ALLOWED', '请求方法不对', http=405)

    user = _session_user(request)
    if user is None:
        return _err('USER_INVALID', '用户不存在或已注销，请重新登录', http=401)

    activity_id = None
    raw = _param(request, 'activity_id')
    if raw is not None and str(raw).strip():
        raw = str(raw).strip()
        if not raw.isdigit():
            return _err('BAD_REQUEST', 'activity_id 不合法', http=400,
                        activity_id=None)
        activity_id = int(raw)

    try:
        result = SignInService(
            user,
            activity_id=activity_id,
            client_ip=client_ip(request),
        ).execute()
    except Exception:
        # 正常业务结果不会走到这里（execute 内部已消化 DatabaseError）。
        # 能到这里说明是代码缺陷 —— 日志里留全量堆栈，给用户只回一句人话。
        logger.exception(
            '签到接口未预期异常 uid=%s activity_id=%s',
            getattr(user, 'uid', None), activity_id,
        )
        return _err('INTERNAL_ERROR', '系统繁忙，请稍后重试', http=500)

    payload = dict(result)
    payload['status'] = 'success' if result.get('ok') else 'error'
    return JsonResponse(payload)
