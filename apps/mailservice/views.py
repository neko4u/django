# apps/mailservice/views.py
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .codes import (
    SCENES,
    MailRateLimitError,
    MailSendError,
    get_ticket,
    issue_ticket,
    mask_email,
    normalize_email,
    send_code,
    verify_code,
)

logger = logging.getLogger(__name__)
ANONYMOUS_SCENES = ('change_pwd', 'reset_pwd')


def client_ip(request):
    """取真实客户端 IP（项目部署在代理后面）"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _current_user(request):
    """已登录则返回 UserInfo，否则 None"""
    if not request.session.get('is_logged_in'):
        return None
    uid = (request.session.get('info') or {}).get('uid')
    if not uid:
        return None
    from apps.login.models import UserInfo
    return UserInfo.objects.filter(uid=uid).first()


def _resolve_target(request, scene):
    """决定验证码要发到哪个邮箱。

    返回 (email, error_response)：
      - change_email：必须是当前登录账号已绑定的**旧邮箱**（防止改成别人的邮箱）
      - 已登录的其他场景：发到当前账号邮箱
      - 未登录：用户输入的邮箱（模糊响应，防账号枚举）
    """
    user = _current_user(request)

    if scene == 'change_email':
        if not user:
            return None, JsonResponse(
                {'success': False, 'message': '请先登录'}, status=401
            )
        email = (user.email or '').strip()
        if not email:
            return None, JsonResponse({
                'success': False,
                'message': '当前账号未绑定邮箱，请联系管理员',
            })
        return email, None

    if user:
        email = (user.email or '').strip()
        if not email:
            return None, JsonResponse({
                'success': False,
                'message': '当前账号未绑定邮箱，请联系管理员',
            })
        return email, None

    if scene not in ANONYMOUS_SCENES:
        return None, JsonResponse(
            {'success': False, 'message': '请先登录'}, status=401
        )

    email = normalize_email(request.POST.get('email'))
    if not email or '@' not in email:
        return None, JsonResponse(
            {'success': False, 'message': '请填写正确的邮箱格式'}
        )

    from apps.login.models import UserInfo
    count = UserInfo.objects.filter(email__iexact=email).count()
    if count == 0:
        logger.info(f'找回密码请求的邮箱未注册: {mask_email(email)}')
        return None, JsonResponse({
            'success': True,
            'message': '验证码已发送，请查收邮件（若长时间未收到请确认邮箱是否正确）',
            'sent': False,
        })
    if count > 1:
        return None, JsonResponse({
            'success': False,
            'message': '该邮箱绑定了多个账号，请联系管理员处理',
        })
    return email, None


@require_POST
def send_email_code(request):
    """POST /api/send-email-code/  { email?, scene }"""
    scene = (request.POST.get('scene') or 'change_pwd').strip()
    if scene not in SCENES:
        return JsonResponse({'success': False, 'message': '未知的验证码场景'}, status=400)

    target_email, error_response = _resolve_target(request, scene)
    if error_response is not None:
        return error_response

    try:
        send_code(target_email, scene, ip=client_ip(request))
    except MailRateLimitError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=429)
    except MailSendError as exc:
        return JsonResponse({'success': False, 'message': str(exc)})

    return JsonResponse({
        'success': True,
        'sent': True,
        'message': f'验证码已发送至 {mask_email(target_email)}，请查收',
    })


@require_POST
def verify_email_code(request):
    """POST /api/verify-email-code/  { email?, code, scene }  ->  ticket"""
    scene = (request.POST.get('scene') or 'change_pwd').strip()
    if scene not in SCENES:
        return JsonResponse({'success': False, 'message': '未知的验证码场景'}, status=400)

    code = (request.POST.get('code') or '').strip()

    user = _current_user(request)
    if user and (user.email or '').strip():
        target_email = (user.email or '').strip()
    else:
        target_email = normalize_email(request.POST.get('email'))

    if not target_email or not verify_code(target_email, scene, code):
        return JsonResponse({'success': False, 'message': '验证码错误或已过期'})

    ticket = issue_ticket(target_email, scene)
    return JsonResponse({'success': True, 'message': '验证通过', 'ticket': ticket})


@require_POST
def check_email_ticket(request):
    """POST /api/check-email-ticket/  { ticket, scene }  -> 仅探测有效性

    给前端做「验证码是否已通过」的状态确认用，不消费 ticket。
    """
    scene = (request.POST.get('scene') or '').strip() or None
    payload = get_ticket((request.POST.get('ticket') or '').strip(), scene)
    if not payload:
        return JsonResponse({'success': False, 'message': '验证已失效'})
    return JsonResponse({
        'success': True,
        'email': payload.get('email', ''),
        'scene': payload.get('scene', ''),
    })
