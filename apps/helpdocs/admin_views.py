# apps/helpdocs/admin_views.py
"""帮助中心的后台页面与接口（都在 /suadmin/ 下）。
"""

import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.suadmin.decorators import require_perm, require_perm_api
from apps.suadmin.permissions import (
    PERM_HELPCENTER_DOC_EDIT,
    PERM_HELPCENTER_DOC_VIEW,
)

from .models import HelpCenterDoc
from .sanitize import clean_html, html_to_markdown

logger = logging.getLogger(__name__)


@require_perm(PERM_HELPCENTER_DOC_VIEW)
def doc_index(request):
    """入口页：输入 docid 进入编辑；或新建一篇。"""
    message = ''

    if request.method == 'POST':
        # --- 新建 ---
        if request.POST.get('action') == 'create':
            title = (request.POST.get('title') or '').strip()[:200] or '新文档'
            doc = HelpCenterDoc.objects.create(title=title)
            return redirect('helpdoc_admin_edit', docid=doc.docid)

        # --- 按 docid 打开 ---
        raw = (request.POST.get('docid') or '').strip()
        if not raw.isdigit():
            message = 'docid 必须是一个数字'
        else:
            docid = int(raw)
            if not HelpCenterDoc.objects.filter(docid=docid).exists():
                message = '找不到这个文档（docid=%s）' % docid
            else:
                return redirect('helpdoc_admin_edit', docid=docid)

    return render(request, 'helpdocs/admin/doc_index.html', {'message': message})


@require_perm(PERM_HELPCENTER_DOC_VIEW)
def doc_edit(request, docid):
    """编辑页：读出一篇文档的原始 HTML。"""
    doc = get_object_or_404(HelpCenterDoc, docid=docid)
    return render(request, 'helpdocs/admin/doc_edit.html', {'doc': doc})


@require_perm_api(PERM_HELPCENTER_DOC_EDIT)
@require_http_methods(['POST'])
def doc_save(request):
    """保存文档。

    流程：原始 HTML -> 整段删 script/style -> bleach 白名单清洗
                -> 自动转 Markdown -> 落库
    """
    raw_docid = (request.POST.get('docid') or '').strip()
    if not raw_docid.isdigit():
        return JsonResponse({'status': 'error', 'message': 'docid 参数不合法'}, status=400)

    doc = HelpCenterDoc.objects.filter(docid=int(raw_docid)).first()
    if doc is None:
        return JsonResponse({'status': 'error', 'message': '文档不存在'}, status=404)

    raw_html = request.POST.get('content_html') or ''
    title = (request.POST.get('title') or '').strip()[:200]

    safe_html = clean_html(raw_html)
    markdown = html_to_markdown(safe_html)

    doc.title = title
    doc.content_html = safe_html
    doc.content_md = markdown
    doc.save()

    logger.info('帮助中心文档已保存 docid=%s 管理员=%s html=%d字 md=%d字',
                doc.docid, request.session.get('info', {}).get('uid'),
                len(safe_html), len(markdown))

    return JsonResponse({
        'status': 'success',
        'message': '已保存',
        'docid': doc.docid,
        'updated_at': doc.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        'html_length': len(safe_html),
        'md_length': len(markdown),
    })



import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.suadmin.permissions import (
    PERM_HELPCENTER_IMAGE_DELETE,
    PERM_HELPCENTER_IMAGE_UPLOAD,
)

from .models import HelpCenterImage


MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Pillow 真正解出来的格式 -> 落盘扩展名。
# 以「真实格式」为准，不信任客户端给的文件名（.php 改名成 .png 也拦得住）。
FORMAT_EXT = {'png': 'png', 'jpeg': 'jpg', 'gif': 'gif', 'webp': 'webp', 'bmp': 'bmp'}


@require_perm_api(PERM_HELPCENTER_IMAGE_UPLOAD)
@require_http_methods(['POST'])
def image_upload(request):
    """上传一张图片，落盘 + 在 helpcenter_image 记一行（该文档的图片列表用它）。"""
    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'status': 'error', 'message': '没有收到文件'}, status=400)

    if upload.size > MAX_IMAGE_BYTES:
        return JsonResponse(
            {'status': 'error',
             'message': '图片不能超过 %d MB' % (MAX_IMAGE_BYTES // 1048576)},
            status=400)

    data = upload.read()
    if not data:
        return JsonResponse({'status': 'error', 'message': '文件是空的'}, status=400)

    # 真解码一次才认。Pillow 解不开的（改名的脚本、损坏文件）一律拒绝。
    try:
        from PIL import Image
        im = Image.open(BytesIO(data))
        fmt = (im.format or '').lower()
        im.verify()
    except Exception as exc:
        logger.warning('拒绝无效图片 name=%r size=%s: %s', upload.name, upload.size, exc)
        return JsonResponse({'status': 'error', 'message': '这不是一张有效的图片'}, status=400)

    ext = FORMAT_EXT.get(fmt)
    if ext is None:
        return JsonResponse(
            {'status': 'error', 'message': '只支持 png / jpg / gif / webp / bmp 格式'},
            status=400)

    # docid 允许缺省（新建文档还没保存就先传图），这种情况下落到 help/0/
    doc = None
    raw_docid = (request.POST.get('docid') or '').strip()
    if raw_docid.isdigit():
        doc = HelpCenterDoc.objects.filter(docid=int(raw_docid)).first()

    stamp = timezone.now().strftime('%Y%m%d')
    filename = '%s-%s.%s' % (stamp, uuid.uuid4().hex[:8], ext)
    file_key = default_storage.save(
        'help/%s/%s' % (doc.docid if doc else 0, filename), ContentFile(data))

    image = HelpCenterImage.objects.create(
        doc=doc,
        file_key=file_key,
        original_name=(upload.name or '')[:255],
        file_size=len(data),
    )

    logger.info('帮助中心图片已上传 key=%s docid=%s 管理员 uid=%s',
                file_key, doc.docid if doc else None,
                request.session.get('info', {}).get('uid'))

    return JsonResponse({
        'status': 'success',
        'image_id': image.id,
        'file_key': file_key,
        'url': image.file_url,
        'original_name': image.original_name,
        'file_size': image.file_size,
    })


@require_perm_api(PERM_HELPCENTER_DOC_VIEW)
@require_http_methods(['GET'])
def image_list(request):
    """列出某篇文档已上传的图片（供编辑页下方那个列表用）。"""
    raw_docid = (request.GET.get('docid') or '').strip()
    if not raw_docid.isdigit():
        return JsonResponse({'status': 'error', 'message': 'docid 参数不合法'}, status=400)

    images = HelpCenterImage.objects.filter(doc_id=int(raw_docid))
    return JsonResponse({
        'status': 'success',
        'items': [{
            'image_id': im.id,
            'file_key': im.file_key,
            'url': im.file_url,
            'original_name': im.original_name or '',
            'file_size': im.file_size,
            'uploaded_at': im.uploaded_at.strftime('%Y-%m-%d %H:%M:%S'),
        } for im in images],
    })


@require_perm_api(PERM_HELPCENTER_IMAGE_DELETE)
@require_http_methods(['POST'])
def image_delete(request):
    """删除一张图片：先删库记录，再尽力删文件。

    文件删失败只记日志、不报错 —— 库里的记录没了，前台就不会再引用它，
    剩下一个孤儿文件不影响功能（比让用户看到 500 好）。
    """
    raw = (request.POST.get('image_id') or '').strip()
    if not raw.isdigit():
        return JsonResponse({'status': 'error', 'message': 'image_id 参数不合法'}, status=400)

    image = HelpCenterImage.objects.filter(id=int(raw)).first()
    if image is None:
        return JsonResponse({'status': 'error', 'message': '图片不存在'}, status=404)

    file_key = image.file_key
    image.delete()

    try:
        if default_storage.exists(file_key):
            default_storage.delete(file_key)
    except Exception as exc:
        logger.warning('删除图片文件失败 key=%s: %s', file_key, exc)

    logger.info('帮助中心图片已删除 key=%s 管理员 uid=%s', file_key,
                request.session.get('info', {}).get('uid'))

    return JsonResponse({'status': 'success', 'message': '已删除'})
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.suadmin.permissions import (
    PERM_HELPCENTER_IMAGE_DELETE,
    PERM_HELPCENTER_IMAGE_UPLOAD,
)

from .models import HelpCenterImage


MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Pillow 真正解出来的格式 -> 落盘扩展名。
# 以「真实格式」为准，不信任客户端给的文件名（.php 改名成 .png 也拦得住）。
FORMAT_EXT = {'png': 'png', 'jpeg': 'jpg', 'gif': 'gif', 'webp': 'webp', 'bmp': 'bmp'}


@require_perm_api(PERM_HELPCENTER_IMAGE_UPLOAD)
@require_http_methods(['POST'])
def image_upload(request):
    """上传一张图片，落盘 + 在 helpcenter_image 记一行（该文档的图片列表用它）。"""
    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'status': 'error', 'message': '没有收到文件'}, status=400)

    if upload.size > MAX_IMAGE_BYTES:
        return JsonResponse(
            {'status': 'error',
             'message': '图片不能超过 %d MB' % (MAX_IMAGE_BYTES // 1048576)},
            status=400)

    data = upload.read()
    if not data:
        return JsonResponse({'status': 'error', 'message': '文件是空的'}, status=400)

    # 真解码一次才认。Pillow 解不开的（改名的脚本、损坏文件）一律拒绝。
    try:
        from PIL import Image
        im = Image.open(BytesIO(data))
        fmt = (im.format or '').lower()
        im.verify()
    except Exception as exc:
        logger.warning('拒绝无效图片 name=%r size=%s: %s', upload.name, upload.size, exc)
        return JsonResponse({'status': 'error', 'message': '这不是一张有效的图片'}, status=400)

    ext = FORMAT_EXT.get(fmt)
    if ext is None:
        return JsonResponse(
            {'status': 'error', 'message': '只支持 png / jpg / gif / webp / bmp 格式'},
            status=400)

    # docid 允许缺省（新建文档还没保存就先传图），这种情况下落到 help/0/
    doc = None
    raw_docid = (request.POST.get('docid') or '').strip()
    if raw_docid.isdigit():
        doc = HelpCenterDoc.objects.filter(docid=int(raw_docid)).first()

    stamp = timezone.now().strftime('%Y%m%d')
    filename = '%s-%s.%s' % (stamp, uuid.uuid4().hex[:8], ext)
    file_key = default_storage.save(
        'help/%s/%s' % (doc.docid if doc else 0, filename), ContentFile(data))

    image = HelpCenterImage.objects.create(
        doc=doc,
        file_key=file_key,
        original_name=(upload.name or '')[:255],
        file_size=len(data),
    )

    logger.info('帮助中心图片已上传 key=%s docid=%s 管理员 uid=%s',
                file_key, doc.docid if doc else None,
                request.session.get('info', {}).get('uid'))

    return JsonResponse({
        'status': 'success',
        'image_id': image.id,
        'file_key': file_key,
        'url': image.file_url,
        'original_name': image.original_name,
        'file_size': image.file_size,
    })


@require_perm_api(PERM_HELPCENTER_DOC_VIEW)
@require_http_methods(['GET'])
def image_list(request):
    """列出某篇文档已上传的图片（供编辑页下方那个列表用）。"""
    raw_docid = (request.GET.get('docid') or '').strip()
    if not raw_docid.isdigit():
        return JsonResponse({'status': 'error', 'message': 'docid 参数不合法'}, status=400)

    images = HelpCenterImage.objects.filter(doc_id=int(raw_docid))
    return JsonResponse({
        'status': 'success',
        'items': [{
            'image_id': im.id,
            'file_key': im.file_key,
            'url': im.file_url,
            'original_name': im.original_name or '',
            'file_size': im.file_size,
            'uploaded_at': im.uploaded_at.strftime('%Y-%m-%d %H:%M:%S'),
        } for im in images],
    })


@require_perm_api(PERM_HELPCENTER_IMAGE_DELETE)
@require_http_methods(['POST'])
def image_delete(request):
    """删除一张图片：先删库记录，再尽力删文件。

    文件删失败只记日志、不报错 —— 库里的记录没了，前台就不会再引用它，
    剩下一个孤儿文件不影响功能（比让用户看到 500 好）。
    """
    raw = (request.POST.get('image_id') or '').strip()
    if not raw.isdigit():
        return JsonResponse({'status': 'error', 'message': 'image_id 参数不合法'}, status=400)

    image = HelpCenterImage.objects.filter(id=int(raw)).first()
    if image is None:
        return JsonResponse({'status': 'error', 'message': '图片不存在'}, status=404)

    file_key = image.file_key
    image.delete()

    try:
        if default_storage.exists(file_key):
            default_storage.delete(file_key)
    except Exception as exc:
        logger.warning('删除图片文件失败 key=%s: %s', file_key, exc)

    logger.info('帮助中心图片已删除 key=%s 管理员 uid=%s', file_key,
                request.session.get('info', {}).get('uid'))

    return JsonResponse({'status': 'success', 'message': '已删除'})
