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
