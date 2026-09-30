# apps/pointsBalanceSystem/signin_admin_views.py
"""签到活动管理（都在 /suadmin/ 下）。

    GET  /suadmin/points/signin/         活动列表 + 新建 / 编辑表单
    POST /suadmin/points/signin/save/    新建或更新一个活动（返回 JSON）
    POST /suadmin/points/signin/toggle/  启用 / 停用（返回 JSON）

权限码：`points.signin.view`（看页面）/ `points.signin.edit`（改数据）。

⚠️ 依赖顺序（改这个模块时务必遵守）：
   这两个权限码必须先存在于 `apps/suadmin/permissions.py`。
   否则本模块一 import 就 ImportError → `project1/urls.py` 加载失败 → **全站 500**，
   而不是只有这一个页面挂。

约定：
  - 时间只到「分」，前端用 `<input type="datetime-local">`，值形如 `2026-09-30T14:00`
  - 项目 `USE_TZ=False`，全程 naive 本地时间；收到带时区的值会**丢弃时区**（只记 warning）
  - 起止时间由 DB 的 CheckConstraint 兜底（`end_at > start_at`），
    应用层也校验一遍，并把 IntegrityError 转成人话
  - 刻意**不做「删除活动」**：已经有签到记录的活动删掉会留下孤立的引用和流水，
    要停止就用「停用」。
"""

import json
import logging
from datetime import datetime, time

from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.suadmin.decorators import require_perm, require_perm_api
from apps.suadmin.permissions import (
    PERM_POINTS_SIGNIN_EDIT,
    PERM_POINTS_SIGNIN_VIEW,
)

from .models import SignInActivity

logger = logging.getLogger(__name__)

# 单次赠送积分的上限 —— 只是防手滑打出 8 位数，不是业务规则
MAX_POINTS_PER_SIGN_IN = 1000000


# --------------------------------------------------------------------------- 小工具


def _json_err(message, code='BAD_REQUEST', http=400):
    return JsonResponse({'status': 'error', 'code': code, 'message': message}, status=http)


def _json_ok(**data):
    payload = {'status': 'success', 'message': '已保存'}
    payload.update(data)
    return JsonResponse(payload)


def _param(request, name):
    """取参数：POST 表单优先，其次 query，最后 JSON body。"""
    val = request.POST.get(name)
    if val is None:
        val = request.GET.get(name)
    if val is None and (request.content_type or '').startswith('application/json'):
        try:
            body = json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            body = {}
        if isinstance(body, dict) and body.get(name) is not None:
            val = str(body.get(name))
    return val


def _parse_dt(raw):
    """解析成 naive datetime。返回 (dt, 错误信息)。"""
    raw = (raw or '').strip()
    if not raw:
        return None, '时间不能为空'

    dt = parse_datetime(raw)
    if dt is None:
        # 允许只给日期（等价于当天 00:00）
        d = parse_date(raw)
        if d is not None:
            dt = datetime.combine(d, time(0, 0))
        else:
            return None, '时间格式不对（应为 2026-09-30T14:00）'

    if dt.tzinfo is not None:
        # 正常情况不会走到这里：datetime-local 不带时区。
        # 真带了也不敢按它换算（项目全站 naive/CST），丢掉时区按本地墙钟时间处理，并记 warning。
        logger.warning('签到活动时间收到带时区的值 %r，已丢弃时区信息', raw)
        dt = dt.replace(tzinfo=None)

    return dt, None


def _fmt_local(dt):
    """给 <input type="datetime-local"> 用的值：2026-09-30T14:00"""
    return dt.strftime('%Y-%m-%dT%H:%M')


def _state_of(activity, now):
    """返回 (状态文案, CSS 类名)。"""
    if not activity.enable:
        return '已停用', 'off'
    if now < activity.start_at:
        return '未开始', 'wait'
    if now > activity.end_at:
        return '已结束', 'done'
    return '进行中', 'on'


# --------------------------------------------------------------------------- 页面


@require_perm(PERM_POINTS_SIGNIN_VIEW)
def activity_index(request):
    """活动列表 + 新建/编辑表单。"""
    if request.method != 'GET':
        return JsonResponse({'status': 'error', 'message': '请求方法不对'}, status=405)

    now = timezone.now()
    rows = []
    for a in SignInActivity.objects.all():
        state, state_cls = _state_of(a, now)
        rows.append({
            'a': a,
            'state': state,
            'state_cls': state_cls,
            'start_text': a.start_at.strftime('%Y-%m-%d %H:%M'),
            'end_text': a.end_at.strftime('%Y-%m-%d %H:%M'),
            'start_local': _fmt_local(a.start_at),
            'end_local': _fmt_local(a.end_at),
        })

    # 给前端「编辑」按钮回填表单用。
    # ⚠️ 必须把 < 转义成 \u003c：活动名里如果出现 </script> 会把整个 JSON 块截断，
    #    变成 XSS 入口。（json.dumps 只保证 JSON 合法，不保证 HTML 安全。）
    rows_json = json.dumps([{
        'id': r['a'].id,
        'name': r['a'].name,
        'description': r['a'].description or '',
        'enable': bool(r['a'].enable),
        'points': r['a'].points_per_sign_in,
        'start_local': r['start_local'],
        'end_local': r['end_local'],
        'state': r['state'],
    } for r in rows], ensure_ascii=False).replace('<', '\\u003c')

    return render(request, 'pointsBalanceSystem/admin/signin_activity.html', {
        'rows': rows,
        'rows_json': rows_json,
        'now_text': now.strftime('%Y-%m-%d %H:%M'),
        'msg': (request.GET.get('msg') or '').strip()[:200],
        'max_points': MAX_POINTS_PER_SIGN_IN,
    })


# --------------------------------------------------------------------------- 写接口


@require_perm_api(PERM_POINTS_SIGNIN_EDIT)
def activity_save(request):
    """新建或更新一个活动。

    参数：
        activity_id  （可选）有 = 更新，没有 = 新建
        name         活动名称（必填，≤128）
        description  活动说明（可空）
        start_at     开始时间（必填，datetime-local 格式）
        end_at       结束时间（必填）
        points_per_sign_in  每次赠送积分（0 ~ 1000000）
        enable       1 / 0
    """
    if request.method != 'POST':
        return _json_err('请求方法不对', code='METHOD_NOT_ALLOWED', http=405)

    # ---------------- 名称 ----------------
    name = (_param(request, 'name') or '').strip()[:128]
    if not name:
        return _json_err('活动名称不能为空')

    # ---------------- 积分 ----------------
    raw_points = (_param(request, 'points_per_sign_in') or '').strip()
    if not raw_points.isdigit():
        return _json_err('每次赠送积分必须是不小于 0 的整数')
    points = int(raw_points)
    if points > MAX_POINTS_PER_SIGN_IN:
        return _json_err('每次赠送积分不能超过 %d' % MAX_POINTS_PER_SIGN_IN)

    # ---------------- 时间 ----------------
    start_at, err = _parse_dt(_param(request, 'start_at'))
    if err:
        return _json_err('开始时间：%s' % err)
    end_at, err = _parse_dt(_param(request, 'end_at'))
    if err:
        return _json_err('结束时间：%s' % err)

    if end_at <= start_at:
        return _json_err('结束时间必须晚于开始时间（当前填的是 %s → %s）' % (
            start_at.strftime('%Y-%m-%d %H:%M'), end_at.strftime('%Y-%m-%d %H:%M')))

    # ---------------- 定位记录 ----------------
    raw_id = (_param(request, 'activity_id') or '').strip()
    if raw_id:
        if not raw_id.isdigit():
            return _json_err('activity_id 不合法')
        activity = SignInActivity.objects.filter(pk=int(raw_id)).first()
        if activity is None:
            return _json_err('活动不存在', code='NOT_FOUND', http=404)
        created = False
    else:
        activity = SignInActivity()
        created = True

    # ---------------- 写 ----------------
    activity.name = name
    activity.description = (_param(request, 'description') or '').strip()
    activity.start_at = start_at
    activity.end_at = end_at
    activity.points_per_sign_in = points
    raw_enable = _param(request, 'enable')
    activity.enable = True if raw_enable is None else raw_enable in ('1', 'true', 'True', 'on', 'yes')

    try:
        activity.save()
    except IntegrityError as exc:
        # DB 上的 CheckConstraint（end_at > start_at）兜底。
        # 正常情况下上面已经拦过了，走到这里说明有别的约束被碰了 —— 一律给人话。
        logger.warning('保存签到活动碰到约束 name=%r id=%s: %s', name, raw_id or None, exc)
        return _json_err('保存失败：数据不满足约束（请检查时间区间）', code='CONSTRAINT', http=400)

    logger.info('签到活动已%s id=%s name=%r 启用=%s %s ~ %s 每次=%d 管理员=%s',
                '新建' if created else '更新', activity.id, activity.name, activity.enable,
                activity.start_at, activity.end_at, activity.points_per_sign_in,
                request.session.get('info', {}).get('uid'))

    return _json_ok(
        message='已%s活动「%s」' % ('新建' if created else '保存', activity.name),
        activity_id=activity.id,
        created=created,
    )


@require_perm_api(PERM_POINTS_SIGNIN_EDIT)
def activity_toggle(request):
    """启用 / 停用一个活动。

    参数：activity_id（必填）、enable（1 / 0，必填）
    """
    if request.method != 'POST':
        return _json_err('请求方法不对', code='METHOD_NOT_ALLOWED', http=405)

    raw_id = (_param(request, 'activity_id') or '').strip()
    if not raw_id.isdigit():
        return _json_err('activity_id 不合法')

    activity = SignInActivity.objects.filter(pk=int(raw_id)).first()
    if activity is None:
        return _json_err('活动不存在', code='NOT_FOUND', http=404)

    raw_enable = (_param(request, 'enable') or '').strip()
    if raw_enable not in ('0', '1', 'true', 'false', 'True', 'False', 'on', 'off'):
        return _json_err('enable 只能是 1 或 0')
    enable = raw_enable in ('1', 'true', 'True', 'on')

    if activity.enable == enable:
        return _json_ok(message='活动「%s」本来就是%s的' % (
            activity.name, '启用' if enable else '停用'), activity_id=activity.id)

    activity.enable = enable
    activity.save(update_fields=['enable', 'updated_at'])

    logger.info('签到活动%s id=%s name=%r 管理员=%s',
                '启用' if enable else '停用', activity.id, activity.name,
                request.session.get('info', {}).get('uid'))

    return _json_ok(message='活动「%s」已%s' % (activity.name, '启用' if enable else '停用'),
                    activity_id=activity.id)
