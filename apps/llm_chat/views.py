import json
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from login.decorators import login_required_api
from .decorators import (
    require_chat_access,
    superadmin_required_api,
)
from . import services
from .models import UserPermission, LLMTask
from login.decorators import login_required_view
from apps.llm_config.models import LLMProvider
from django.views.decorators.http import require_GET


@login_required_view
def chat_page(request):
    return render(request, 'chat.html')

@csrf_exempt
@login_required_api
@require_chat_access
def new_conversation(request):
    if request.method != 'POST':
        return JsonResponse({'error': '方法不允许'}, status=405)
    uid = request.session['info']['uid']
    conv = services.create_conversation(uid)
    return JsonResponse({'conversation_id': conv.id})


@csrf_exempt
@login_required_api
@require_chat_access
def list_conversations(request):
    uid = request.session['info']['uid']
    convs = services.get_conversations(uid)
    data = [{
        'id': c.id,
        'title': c.title,
        'updated_at': c.updated_at.isoformat(),
    } for c in convs]
    return JsonResponse(data, safe=False)


@csrf_exempt
@login_required_api
@require_chat_access
def send_message(request, conversation_id):
    if request.method != 'POST':
        return JsonResponse({'error': '方法不允许'}, status=405)
    try:
        body = json.loads(request.body.decode('utf-8'))
        user_message = body.get('message', '')
    except Exception:
        return JsonResponse({'error': '请求格式错误'}, status=400)
    if not user_message:
        return JsonResponse({'error': '消息不能为空'}, status=400)
    uid = request.session['info']['uid']

    def event_stream():
        try:
            for chunk in services.send_message_stream(conversation_id, uid, user_message):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'服务器内部错误: {str(e)}'})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@csrf_exempt
@login_required_api
@require_chat_access
def get_messages(request, conversation_id):
    uid = request.session['info']['uid']
    msgs = services.get_messages(conversation_id, uid)
    if msgs is None:
        return JsonResponse({'error': '对话不存在'}, status=404)
    data = [{'role': m.role, 'content': m.content, 'created_at': m.created_at.isoformat()} for m in msgs]
    return JsonResponse(data, safe=False)


@csrf_exempt
@login_required_api
@require_chat_access
def rename_conversation(request, conversation_id):
    if request.method != 'PATCH':
        return JsonResponse({'error': '方法不允许'}, status=405)
    try:
        body = json.loads(request.body.decode('utf-8'))
        new_title = body.get('title', '').strip()
    except:
        return JsonResponse({'error': '请求格式错误'}, status=400)
    if not new_title:
        return JsonResponse({'error': '标题不能为空'}, status=400)
    uid = request.session['info']['uid']
    success = services.rename_conversation(conversation_id, uid, new_title)
    if not success:
        return JsonResponse({'error': '对话不存在或无权操作'}, status=404)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@login_required_api
@require_chat_access
def delete_conversation(request, conversation_id):
    if request.method != 'DELETE':
        return JsonResponse({'error': '方法不允许'}, status=405)
    uid = request.session['info']['uid']
    success = services.delete_conversation(conversation_id, uid)
    if not success:
        return JsonResponse({'error': '对话不存在或无权操作'}, status=404)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@login_required_api
@require_chat_access
def get_config(request, conversation_id):
    uid = request.session['info']['uid']
    config = services.get_config(conversation_id, uid)
    if config is None:
        return JsonResponse({'error': '对话不存在'}, status=404)
    return JsonResponse(config)


@csrf_exempt
@login_required_api
def update_config(request, conversation_id):
    uid = request.session['info']['uid']
    try:
        perm = UserPermission.objects.get(uid=uid)
    except UserPermission.DoesNotExist:
        return JsonResponse({'error': '无权限'}, status=403)

    if not (perm.can_set_temperature or perm.can_set_top_p or perm.can_set_presence_penalty
            or perm.can_set_frequency_penalty or perm.can_set_max_tokens):
        return JsonResponse({'error': '无权限'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': '方法不允许'}, status=405)
    try:
        body = json.loads(request.body.decode('utf-8'))
    except:
        return JsonResponse({'error': '请求格式错误'}, status=400)

    allowed_fields = {
        'temperature': perm.can_set_temperature,
        'max_tokens': perm.can_set_max_tokens,
        'top_p': perm.can_set_top_p,
        'presence_penalty': perm.can_set_presence_penalty,
        'frequency_penalty': perm.can_set_frequency_penalty,
    }
    update_data = {}
    for field, allowed in allowed_fields.items():
        if field in body:
            if not allowed:
                return JsonResponse({'error': f'无权修改参数 {field}'}, status=403)
            update_data[field] = body[field]
    if 'web_search_enabled' in body:
        update_data['web_search_enabled'] = body['web_search_enabled']
    if 'model_name' in body:
        update_data['model_name'] = body['model_name']

    if not update_data:
        return JsonResponse({'error': '无有效参数'}, status=400)

    success = services.update_config(conversation_id, uid, **update_data)
    if not success:
        return JsonResponse({'error': '对话不存在或无权操作'}, status=404)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@login_required_api
@require_chat_access
def stop_generation(request):
    if request.method != 'POST':
        return JsonResponse({'error': '方法不允许'}, status=405)
    try:
        body = json.loads(request.body.decode('utf-8'))
        conversation_id = body.get('conversation_id')
    except:
        return JsonResponse({'error': '请求格式错误'}, status=400)
    if not conversation_id:
        return JsonResponse({'error': '缺少 conversation_id'}, status=400)
    uid = request.session['info']['uid']
    success = services.stop_generation(conversation_id, uid)
    if not success:
        return JsonResponse({'error': '对话不存在或无权操作'}, status=404)
    return JsonResponse({'status': 'ok'})


@csrf_exempt
@login_required_api
@require_chat_access
def generate_title(request, conversation_id):
    if request.method != 'POST':
        return JsonResponse({'error': '方法不允许'}, status=405)
    uid = request.session['info']['uid']
    title = services.generate_title(conversation_id, uid)
    if not title:
        return JsonResponse({'error': '生成标题失败'}, status=400)
    return JsonResponse({'title': title})


# 管理员视图
@login_required_api
@superadmin_required_api
def admin_tasks_page(request):
    return render(request, 'admin_tasks.html')


@login_required_api
@superadmin_required_api
def admin_tasks_data(request):
    tasks = LLMTask.objects.all().order_by('-created_at')
    data = []
    for t in tasks:
        data.append({
            'id': t.id,
            'uid': t.uid_id,
            'conversation_id': t.conversation_id,
            'model_name': t.model_name,
            'status': t.status,
            'created_at': t.created_at.isoformat(),
            'finished_at': t.finished_at.isoformat() if t.finished_at else None,
            'error_message': t.error_message,
        })
    return JsonResponse(data, safe=False)

@login_required_api
def get_permissions(request):
    uid = request.session['info']['uid']
    try:
        perm = UserPermission.objects.get(uid=uid)
    except UserPermission.DoesNotExist:
        perm = None
    data = {
        'can_access_chat': perm.can_access_chat if perm else False,
        'can_set_temperature': perm.can_set_temperature if perm else False,
        'can_set_top_p': perm.can_set_top_p if perm else False,
        'can_set_presence_penalty': perm.can_set_presence_penalty if perm else False,
        'can_set_frequency_penalty': perm.can_set_frequency_penalty if perm else False,
        'can_set_max_tokens': perm.can_set_max_tokens if perm else False,
        'can_set_model': True,
        'is_superadmin': perm.is_superadmin if perm else False,
    }
    return JsonResponse(data)

@require_GET
@login_required_api
def get_models(request):
    providers = LLMProvider.objects.filter(is_active=True)
    models = []
    for p in providers:
        for m in p.model_list:
            if not any(x['id'] == m for x in models):
                models.append({'id': m, 'name': m})
    return JsonResponse(models, safe=False)

@login_required_api
def web_search_check(request):
    model_name = request.GET.get('model_name', '')
    supported = False
    if model_name:
        from apps.llm_config.models import LLMProvider
        providers = LLMProvider.objects.filter(is_active=True)
        for p in providers:
            if model_name in p.model_list:
                model_cfg = p.model_config.get(model_name, {})
                supported = model_cfg.get('web_search', False)
                break
    return JsonResponse({'supported': supported})