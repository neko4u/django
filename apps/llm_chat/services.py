import json
import requests
from django.core.cache import cache
from django.utils import timezone
from .models import Conversation, Message, ConversationConfig, LLMTask
from .tasks import create_llm_task, update_task_status
from apps.llm_config.models import LLMProvider


def get_default_provider():
    cache_key = 'default_llm_provider'
    provider = cache.get(cache_key)
    if not provider:
        try:
            provider = LLMProvider.objects.get(is_default=True, is_active=True)
        except LLMProvider.DoesNotExist:
            raise ValueError('没有可用的默认LLM提供商，请在数据库 llm_provider 表中设置 is_default=True 的记录')
        cache.set(cache_key, provider, 60 * 60)
    return provider

def get_provider_by_model(model_name):
    providers = LLMProvider.objects.filter(is_active=True)
    for p in providers:
        if model_name in p.model_list:
            return p
    return get_default_provider()

def estimate_tokens(text):
    return len(text) // 2
    # 估算token,后期需要加入积分系统?

def create_conversation(uid):
    conv = Conversation.objects.create(uid_id=uid, title='新对话')
    # 获取默认模型
    default_model = 'moonshot-v1-8k'  # 最终兜底
    try:
        provider = get_default_provider()
        # 如果有 default_model 字段，优先使用
        if hasattr(provider, 'default_model') and provider.default_model:
            default_model = provider.default_model
        elif provider.model_list:
            default_model = provider.model_list[0]
    except:
        pass
    ConversationConfig.objects.create(conversation=conv, model_name=default_model)
    return conv

def get_conversations(uid):
    return Conversation.objects.filter(uid_id=uid, is_deleted=False)

def get_messages(conversation_id, uid):
    # 验证对话所属权
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        return None
    return Message.objects.filter(conversation=conv)

def rename_conversation(conversation_id, uid, new_title):
    conv = Conversation.objects.filter(id=conversation_id, uid_id=uid, is_deleted=False).first()
    if not conv:
        return False
    conv.title = new_title
    conv.save()
    return True

def delete_conversation(conversation_id, uid):
    conv = Conversation.objects.filter(id=conversation_id, uid_id=uid, is_deleted=False).first()
    if not conv:
        return False
    conv.is_deleted = True
    conv.save()
    return True

def get_config(conversation_id, uid):
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        return None
    try:
        config = ConversationConfig.objects.get(conversation=conv)
        return {
            'model_name': config.model_name,
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
            'top_p': config.top_p,
            'presence_penalty': config.presence_penalty,
            'frequency_penalty': config.frequency_penalty,
            'web_search_enabled': config.web_search_enabled,
        }
    except ConversationConfig.DoesNotExist:
        return None

def update_config(conversation_id, uid, **kwargs):
    conv = Conversation.objects.filter(id=conversation_id, uid_id=uid, is_deleted=False).first()
    if not conv:
        return False
    config, _ = ConversationConfig.objects.get_or_create(conversation=conv)
    allowed_fields = ['model_name', 'temperature', 'max_tokens', 'top_p', 
                      'presence_penalty', 'frequency_penalty', 'web_search_enabled']
    for field, value in kwargs.items():
        if field in allowed_fields:
            setattr(config, field, value)
    config.save()
    return True

def send_message_stream(conversation_id, uid, user_message):
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        yield json.dumps({'error': '对话不存在'})
        return

    Message.objects.create(conversation=conv, role='user', content=user_message)
    config = ConversationConfig.objects.get(conversation=conv)
    provider = get_provider_by_model(config.model_name)

    system_prompt = "You are a helpful assistant."

    all_messages = list(Message.objects.filter(conversation=conv).order_by('created_at'))
    if all_messages:
        all_messages.pop()

    max_context = provider.max_context_tokens if provider.max_context_tokens else 8192
    output_tokens = config.max_tokens
    system_tokens = estimate_tokens(system_prompt)
    available_tokens = max_context - output_tokens - system_tokens - 100

    messages = [{"role": "system", "content": system_prompt}]
    total_tokens = system_tokens

    reversed_history = reversed(all_messages)
    included_history = []
    for msg in reversed_history:
        msg_tokens = estimate_tokens(msg.content)
        if total_tokens + msg_tokens <= available_tokens:
            included_history.insert(0, msg)
            total_tokens += msg_tokens
        else:
            break

    for msg in included_history:
        msg_obj = {"role": msg.role, "content": msg.content}
        if msg.role == 'assistant' and msg.reasoning_content:
            msg_obj['reasoning_content'] = msg.reasoning_content
        messages.append(msg_obj)

    last_assistant_msg = None
    for msg in reversed(included_history):
        if msg.role == 'assistant':
            last_assistant_msg = msg
            break
    if last_assistant_msg and getattr(last_assistant_msg, 'model_name', None) and last_assistant_msg.model_name != config.model_name:
        switch_notice = f"[系统提示] 用户已将对话模型切换为 {config.model_name}，请继续自然对话。"
        messages.append({"role": "system", "content": switch_notice})

    messages.append({"role": "user", "content": user_message})

    enable_search = False
    model_cfg = {}  # 初始化，避免 UnboundLocalError
    if config.web_search_enabled:
        model_cfg = provider.model_config.get(config.model_name, {})
        if model_cfg.get('web_search', False):
            enable_search = True

    task = create_llm_task(uid, conv, config.model_name)

    payload = {
        'model': config.model_name,
        'messages': messages,
        'temperature': config.temperature,
        'max_tokens': config.max_tokens,
        'top_p': config.top_p,
        'presence_penalty': config.presence_penalty,
        'frequency_penalty': config.frequency_penalty,
        'stream': True,
    }

    if enable_search:
        tool_list = model_cfg.get('web_search_tool', [{"type": "web_search", "web_search": {"enable": True}}])
        if tool_list:
            search_config = tool_list[0].get('web_search', {})
        else:
            search_config = {"enable": True}
        payload['web_search'] = search_config
        print('DEBUG payload web_search:', payload.get('web_search'))
        print('DEBUG config.web_search_enabled:', config.web_search_enabled)
        print('DEBUG model_cfg:', model_cfg)

    try:
        response = requests.post(
            f'{provider.base_url.rstrip("/")}/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {provider.api_key}',
            },
            json=payload,
            stream=True,
            timeout=90
        )
        response.raise_for_status()
    except Exception as e:
        update_task_status(task, 'failed', error=str(e))
        yield json.dumps({'error': f'请求失败: {str(e)}'})
        return

    update_task_status(task, 'processing')

    full_content = []
    full_reasoning = []
    stop_key = f'stop_flag:{conversation_id}'
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data_str = line[6:]
            if data_str == '[DONE]':
                break
            try:
                data = json.loads(data_str)
                delta = data['choices'][0]['delta']
                content = delta.get('content', '')
                if content:
                    full_content.append(content)
                    yield json.dumps({'content': content})
                reasoning = delta.get('reasoning_content', '')
                if reasoning:
                    full_reasoning.append(reasoning)
                    yield json.dumps({'reasoning': reasoning})  # 向前端发送思考内容
                if cache.get(stop_key):
                    update_task_status(task, 'failed', error='用户停止生成')
                    yield json.dumps({'stopped': True})
                    return
            except (json.JSONDecodeError, KeyError):
                continue

    assistant_content = ''.join(full_content)
    assistant_reasoning = ''.join(full_reasoning)

    Message.objects.create(
        conversation=conv,
        role='assistant',
        content=assistant_content,
        reasoning_content=assistant_reasoning,
        model_name=config.model_name
    )
    update_task_status(task, 'completed')

    if conv.title == '新对话':
        yield json.dumps({'need_title': True})


def stop_generation(conversation_id, uid):
    # 检查对话所属权
    try:
        Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        return False
    # 设置停止标志，有效期 60 秒
    cache.set(f'stop_flag:{conversation_id}', '1', timeout=60)
    return True

def generate_title(conversation_id, uid):
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        return False
    # 获取首条用户消息作为标题生成的素材
    first_msg = Message.objects.filter(conversation=conv, role='user').first()
    if not first_msg:
        return False
    # 使用简单方式生成标题（调用 LLM 取摘要）
    provider = get_default_provider()
    title_model = provider.model_list[0] if provider.model_list else 'kimi-latest'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {provider.api_key}',
    }
    payload = {
        'model': title_model,
        'messages': [
            {'role': 'user', 'content': f'用不超过15个字给以下对话生成一个简短的标题："{first_msg.content}"'}
        ],
        'max_tokens': 20,
        'temperature': 0.5,
    }
    try:
        resp = requests.post(
            f'{provider.base_url}/chat/completions',
            headers=headers,
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
        title = resp.json()['choices'][0]['message']['content'].strip().strip('"')
        conv.title = title
        conv.save()
        return title
    except Exception:
        conv.title = first_msg.content[:10] + '...'
        conv.save()
        return conv.title