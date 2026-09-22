# apps/captcha/views.py

import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import generator, services, store

logger = logging.getLogger(__name__)


def _payload(request):
    """同时兼容 form-data 和 JSON 两种提交方式"""
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body or b'{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return request.POST


@require_GET
def slider_captcha(request):
    """GET /api/slider-captcha/ —— 生成滑块验证码

    响应：token / bg / tile / y / tile_size / width / height / track_width
    **不返回正确答案 x**
    """
    try:
        data = services.create_challenge()
    except generator.CaptchaGenerateError as exc:
        logger.error(f'生成滑块验证码失败: {exc}')
        return JsonResponse({'success': False, 'message': str(exc)}, status=500)
    except store.CaptchaStoreError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=503)

    return JsonResponse({'success': True, **data})


@require_POST
def verify_slider(request):
    """POST /api/verify-slider/ —— 校验拖动结果

    请求：token / x / y / timestamp / track / clientToken
    响应：valid + ticket  失败时给模糊提示
    """
    payload = _payload(request)

    ticket, message = services.verify_challenge(
        token=(payload.get('token') or '').strip(),
        x=payload.get('x'),
        y=payload.get('y'),
        track=payload.get('track'),
        client_token=(payload.get('clientToken') or '').strip(),
    )

    if not ticket:
        return JsonResponse({'success': False, 'valid': False, 'message': message})

    return JsonResponse({'success': True, 'valid': True, 'ticket': ticket, 'message': '验证通过'})
