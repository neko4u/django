# apps/frpServer/admin_views.py
"""FRP 相关的后台页面与接口，都挂在 /suadmin/frp/ 下。

目前只有一件事：新用户注册赠送时长的总开关。
"""

import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.suadmin.decorators import require_perm
from apps.suadmin.permissions import PERM_FRP_GIFT_EDIT, PERM_FRP_GIFT_VIEW

from .models import RegisterGiftConfig, TimeChangeRecord

logger = logging.getLogger(__name__)

# 赠送时长上限（秒）：一年。纯粹防手滑，比如想填 24 结果多打了几个 0
MAX_GIFT_SECONDS = 365 * 24 * 3600

def hours_text(seconds):
    """把秒换成好填的「小时」字符串：整点不带小数点（24 而不是 24.0）。"""
    hours = (seconds or 0) / 3600.0
    if abs(hours - round(hours)) < 1e-9:
        return str(int(round(hours)))
    return ('%.2f' % hours).rstrip('0').rstrip('.')

@require_perm(PERM_FRP_GIFT_VIEW)
def gift_index(request):
    """注册赠送开关页：看当前配置 + 改。"""
    config = RegisterGiftConfig.load_or_create()
    return render(request, 'frpServer/admin/gift_config.html', {
        'config': config,
        'hours_value': hours_text(config.gift_seconds),
        'max_gift_hours': MAX_GIFT_SECONDS // 3600,
        'granted_count': _granted_user_count(),
    })

@require_perm(PERM_FRP_GIFT_EDIT)
@require_http_methods(['POST'])
def gift_save(request):
    """保存开关。"""
    cfg = RegisterGiftConfig.load_or_create()

    enable = (request.POST.get('enable') or '') in ('on', '1', 'true', 'True')
    raw_hours = (request.POST.get('gift_hours') or '').strip()

    try:
        hours = float(raw_hours)
    except ValueError:
        messages.error(request, '赠送时长请填数字（单位：小时），你填的是「%s」' % raw_hours)
        return redirect('frp_gift_admin_index')

    if hours < 0:
        messages.error(request, '赠送时长不能是负数')
        return redirect('frp_gift_admin_index')

    seconds = int(round(hours * 3600))
    if seconds > MAX_GIFT_SECONDS:
        messages.error(request, '赠送时长最多 %d 小时（一年）' % (MAX_GIFT_SECONDS // 3600))
        return redirect('frp_gift_admin_index')

    changed = (cfg.enable != enable) or (cfg.gift_seconds != seconds)
    cfg.enable = enable
    cfg.gift_seconds = seconds
    cfg.updated_by = str((request.session.get('info') or {}).get('uid') or '')
    cfg.save()

    if not changed:
        messages.success(request, '配置没有变化：%s，赠送 %s'
                         % ('开启' if enable else '关闭', cfg.gift_hours_text))
    else:
        logger.info('注册赠送配置改为 enable=%s seconds=%s 管理员=%s',
                    enable, seconds, cfg.updated_by)
        messages.success(request, '已保存：注册赠送「%s」，新注册用户赠送 %s'
                         % ('开启' if enable else '关闭', cfg.gift_hours_text))

    return redirect('frp_gift_admin_index')

def _granted_user_count():
    """统计因为「注册赠送」拿过时长的用户数（按变更记录里的标记，含补发的）。"""
    try:
        return (TimeChangeRecord.objects
                .filter(detail_json__contains='register_gift')
                .values('user_id').distinct().count())
    except Exception as exc:
        # 统计失败不该让页面挂掉
        logger.warning('统计注册赠送用户数失败: %s', exc)
        return 0