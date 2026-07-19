import json
import os
import uuid
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.core.files.storage import default_storage

from .decorators import require_access, require_edit, check_permission
from .services import (
    list_manuals, create_manual, delete_manual,
    list_docs, search_docs, create_doc, update_doc, delete_doc, get_doc_graph,
    list_nodes, get_node, create_node, update_node, delete_node,
    list_edges, create_edge, update_edge, delete_edge,
    list_categories, create_category,
    list_comments, create_comment,
)
from .forms import (
    ManualForm, DocForm, NodeForm, NodeUpdateForm,
    EdgeForm, EdgeUpdateForm, CategoryForm, CommentForm,
)


# ==================== 页面 ====================

@ensure_csrf_cookie
def index(request):
    """故障树主页面"""
    return render(request, 'fault_tree/fault_tree.index')


# ==================== 权限查询 ====================

def api_permission(request):
    """前端查询当前用户的权限状态"""
    return check_permission(request)


# ==================== Manual ====================

@require_access
def api_list_manuals(request):
    return JsonResponse(list_manuals(), safe=False)


@require_edit
def api_create_manual(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = ManualForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    manual = create_manual(**form.cleaned_data)
    return JsonResponse(manual, status=201)


@require_edit
def api_delete_manual(request, manual_id):
    delete_manual(manual_id)
    return JsonResponse({'ok': True})


# ==================== Doc ====================

@require_access
def api_list_docs(request):
    manual_id = request.GET.get('manual_id')
    return JsonResponse(list_docs(manual_id=manual_id), safe=False)


@require_access
def api_search_docs(request):
    q = request.GET.get('q', '')
    if not q:
        return JsonResponse([], safe=False)
    return JsonResponse(search_docs(q), safe=False)


@require_edit
def api_create_doc(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = DocForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    doc = create_doc(**form.cleaned_data)
    return JsonResponse(doc, status=201)


@require_edit
def api_update_doc(request, doc_id):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    doc = update_doc(
        doc_id,
        title=data.get('title'),
        description=data.get('description'),
    )
    return JsonResponse(doc)


@require_edit
def api_delete_doc(request, doc_id):
    delete_doc(doc_id)
    return JsonResponse({'ok': True})


@require_access
def api_get_doc_graph(request, doc_id):
    try:
        graph = get_doc_graph(doc_id)
        return JsonResponse(graph)
    except FaultTreeDoc.DoesNotExist:
        return JsonResponse({'detail': '文档不存在'}, status=404)


# ==================== Node ====================

@require_access
def api_list_nodes(request):
    doc_id = request.GET.get('doc_id')
    return JsonResponse(list_nodes(doc_id=doc_id), safe=False)


@require_access
def api_get_node(request, node_id):
    try:
        return JsonResponse(get_node(node_id))
    except FaultTreeNode.DoesNotExist:
        return JsonResponse({'detail': '节点不存在'}, status=404)


@require_edit
def api_create_node(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = NodeForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    node = create_node(**form.cleaned_data)
    return JsonResponse(node, status=201)


@require_edit
def api_update_node(request, node_id):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = NodeUpdateForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    node = update_node(node_id, **form.cleaned_data)
    return JsonResponse(node)


@require_edit
def api_delete_node(request, node_id):
    delete_node(node_id)
    return JsonResponse({'ok': True})


# ==================== Edge ====================

@require_access
def api_list_edges(request):
    doc_id = request.GET.get('doc_id')
    return JsonResponse(list_edges(doc_id=doc_id), safe=False)


@require_edit
def api_create_edge(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = EdgeForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    edge = create_edge(**form.cleaned_data)
    return JsonResponse(edge, status=201)


@require_edit
def api_update_edge(request, edge_id):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = EdgeUpdateForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    edge = update_edge(edge_id, **form.cleaned_data)
    return JsonResponse(edge)


@require_edit
def api_delete_edge(request, edge_id):
    delete_edge(edge_id)
    return JsonResponse({'ok': True})


# ==================== Category ====================

@require_access
def api_list_categories(request):
    doc_id = request.GET.get('doc_id')
    return JsonResponse(list_categories(doc_id=doc_id), safe=False)


@require_edit
def api_create_category(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = CategoryForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    cat = create_category(**form.cleaned_data)
    return JsonResponse(cat, status=201)


# ==================== Comment ====================

@require_access
def api_list_comments(request):
    node_id = request.GET.get('node_id')
    return JsonResponse(list_comments(node_id=node_id), safe=False)


@require_edit
def api_create_comment(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'detail': '无效的 JSON'}, status=400)
    form = CommentForm(data)
    if not form.is_valid():
        return JsonResponse({'detail': form.errors}, status=400)
    comment = create_comment(**form.cleaned_data)
    return JsonResponse(comment, status=201)


# ==================== 图片上传 ====================

@require_edit
def api_upload_image(request):
    """上传图片，返回可访问的 URL"""
    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'detail': '未提供文件'}, status=400)

    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if file.content_type not in allowed_types:
        return JsonResponse({'detail': '不支持的文件类型'}, status=400)

    # 生成唯一文件名
    ext = os.path.splitext(file.name)[1] or '.png'
    filename = f'fault_tree/{uuid.uuid4().hex}{ext}'
    saved_path = default_storage.save(filename, file)
    url = settings.MEDIA_URL + saved_path

    return JsonResponse({'url': url})
