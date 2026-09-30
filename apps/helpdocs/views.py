# apps/helpdocs/views.py
"""帮助中心前台。

默认**不需要登录**（帮助文档经常要发给还没账号的人看）。
如果以后想要求登录，给这两个视图各加一行装饰器即可：

    from apps.login.decorators import login_required_view

    @login_required_view
    def doc_list(request):
"""

from django.shortcuts import get_object_or_404, render

from .models import HelpCenterDoc
from .toc import inject_heading_ids


def doc_list(request):
    """帮助中心首页：只列前台可见的文档。"""
    docs = HelpCenterDoc.objects.filter(is_visible=True)   # Meta.ordering = ['-updated_at']
    return render(request, 'helpdocs/doc_list.html', {'docs': docs})


def doc_detail(request, docid):
    """文档详情页：左侧 h2~h4 目录 + 右侧正文。

    这里对 content_html 再跑一次 inject_heading_ids：
    新文档在保存时已经注入过，这里是空操作（函数是幂等的）；
    老文档（保存逻辑还没加锚点注入之前存的）会在这里补上 id，
    这样不用重新保存也能有目录。
    """
    # is_visible=False 的文档对前台等同于不存在 -> 直接 404
    doc = get_object_or_404(HelpCenterDoc, docid=docid, is_visible=True)
    body_html, toc = inject_heading_ids(doc.content_html)

    return render(request, 'helpdocs/doc_detail.html', {
        'doc': doc,
        'body_html': body_html,
        'toc': toc,
    })
