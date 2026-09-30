# apps/downloads/admin_views.py
"""客户端版本管理的后台页面与接口，全部挂在 /suadmin/download/ 下。

一个页面搞定两件事：上面「上传新版本」表单，下面历史版本列表（每行带展示开关）。
提示信息走 django.contrib.messages，处理完 redirect 回列表页，避免刷新重复提交。
"""

import logging

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.suadmin.decorators import require_perm
from apps.suadmin.permissions import (
    PERM_DOWNLOAD_VERSION_EDIT,
    PERM_DOWNLOAD_VERSION_VIEW,
)

from . import services
from .conf import conf
from .forms import VersionUploadForm
from .models import ClientVersion

logger = logging.getLogger(__name__)

@require_perm(PERM_DOWNLOAD_VERSION_VIEW)
def version_index(request):
    """版本列表 + 上传表单（同一个页面）。"""
    return render(request, 'downloads/admin/version_list.html', {
        'versions': services.all_versions(),
        'latest': services.latest_enabled(),
        'current_dir': conf.DIR,
        'download_name': conf.FILE_NAME,
        'max_upload_mb': int(conf.UPLOAD_MAX_BYTES) / 1048576.0,
    })

@require_perm(PERM_DOWNLOAD_VERSION_EDIT)
@require_http_methods(['POST'])
def version_upload(request):
    """上传接口：校验版本号 + 文件 -> 落盘算 MD5 -> 写版本表。"""
    form = VersionUploadForm(request.POST, request.FILES)

    if not form.is_valid():
        _flush_errors(request, form)
        return redirect('download_admin_index')

    six = form.six
    display = form.display
    upload = form.cleaned_data['file']
    disk_name = form.disk_name            # 「文件名称」定稿后的名字
    old = services.version_by_six(six)

    if old is not None and not form.cleaned_data['replace']:
        messages.error(request, '版本 %s 已经存在（文件：%s）。要重传请勾选「覆盖重传」。'
                       % (display, old.file_name))
        return redirect('download_admin_index')

    # 同一个文件名已经被别的版本占了：磁盘上就一个文件，两个版本共用会互相覆盖
    holder = ClientVersion.objects.filter(file_name=disk_name).exclude(version=six).first()
    if holder is not None:
        messages.error(request, '文件名称 %s 已经被版本 %s 占用了，请换一个名字。'
                       % (disk_name, holder.display_version))
        return redirect('download_admin_index')

    try:
        _, md5, size = services.store_upload(upload, disk_name)
    except OSError as exc:
        logger.exception('客户端文件落盘失败')
        messages.error(request, '文件写入失败：%s（检查目录 %s 是否存在且可写）'
                       % (exc, conf.DIR))
        return redirect('download_admin_index')

    if old is not None:
        # 覆盖重传：文件名可能变了，旧文件顺手删掉，别在磁盘上留垃圾
        if old.file_name != disk_name:
            services.remove_file(old.file_name)
        old.file_name = disk_name
        old.md5 = md5
        old.file_size = size
        old.enable = form.cleaned_data['enable']
        old.uploaded_at = timezone.now()
        old.uploader_uid = uid_of(request)
        old.save()
        logger.info('客户端版本覆盖重传 v%s -> %s', display, disk_name)
        messages.success(request, '版本 %s 已覆盖重传（%s，%s）'
                         % (display, disk_name, _size_text(size)))
    else:
        try:
            ClientVersion.objects.create(
                version=six,
                file_name=disk_name,
                md5=md5,
                file_size=size,
                enable=form.cleaned_data['enable'],
                uploader_uid=uid_of(request),
            )
        except IntegrityError:
            # 两个管理员同时传同一个版本号，靠 unique 兜底
            services.remove_file(disk_name)
            messages.error(request, '版本 %s 刚被另一个人传上去了，请刷新后重试。' % display)
            return redirect('download_admin_index')
        logger.info('客户端新版本上传 v%s -> %s', display, disk_name)
        messages.success(request, '版本 %s 上传成功（%s，%s）'
                         % (display, disk_name, _size_text(size)))

    return redirect('download_admin_index')

@require_perm(PERM_DOWNLOAD_VERSION_EDIT)
@require_http_methods(['POST'])
def version_toggle(request):
    """历史版本的「是否展示」开关。"""
    six = (request.POST.get('version') or '').strip()
    record = services.version_by_six(six)
    if record is None:
        messages.error(request, '找不到版本 %s' % six)
        return redirect('download_admin_index')

    action = request.POST.get('action') or ''
    if action == 'show':
        want = True
    elif action == 'hide':
        want = False
    else:
        want = not record.enable          # 没给明确动作就翻转一下

    record.enable = want
    record.save(update_fields=['enable'])
    logger.info('客户端版本 v%s 展示状态 -> %s', record.display_version, want)
    messages.success(request, '版本 %s 已设为「%s」'
                     % (record.display_version, '展示' if want else '不展示'))
    return redirect('download_admin_index')

# ==================== 小工具 ====================

def uid_of(request):
    """当前登录用户的 uid（取不到就空串；只用于留痕，不影响功能）。"""
    return str((request.session.get('info') or {}).get('uid') or '')

def _flush_errors(request, form):
    """把表单错误逐条丢给 messages，页面上直接显示出来。"""
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else ''
        for err in errors:
            messages.error(request, ('%s：%s' % (label, err)) if label else str(err))

def _size_text(size):
    if size < 1024:
        return '%d B' % size
    if size < 1048576:
        return '%.1f KB' % (size / 1024.0)
    return '%.1f MB' % (size / 1048576.0)