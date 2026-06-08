import json
import requests
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings
from .models import Conversation, Message, ConversationConfig, LLMTask
from .tasks import create_llm_task, update_task_status
from apps.llm_config.models import LLMProvider
from .tool_service import ToolManager
import logging

logger = logging.getLogger(__name__)


def get_default_provider():
    logger.info('TESTTTTTTTTTTTT')
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
    return Message.objects.filter(conversation=conv).order_by('created_at')

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

def send_message_stream(conversation_id, uid, user_message, enable_tool_calls=False):
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        yield json.dumps({'error': '对话不存在'})
        return

    conv.is_generating = True
    conv.save(update_fields=['is_generating'])
    try:
        Message.objects.create(conversation=conv, role='user', content=user_message)
        config = ConversationConfig.objects.get(conversation=conv)
        provider = get_provider_by_model(config.model_name)
        if enable_tool_calls:
            system_prompt = (
                "You are a helpful assistant."
                "当需要实时信息时，你必须调用 `tavily_search` 函数，"
                "并以标准 JSON 格式返回，禁止输出任何类似 DSML 的文本。"
            )
        else:
            system_prompt = "You are a helpful assistant."

        all_messages = list(Message.objects.filter(conversation=conv).order_by('-created_at'))
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
        tools = ToolManager.get_tools_for_model(config.model_name)
        # logger.info(f"enable_tool_calls={enable_tool_calls}, tools count={len(tools)}")
        payload = {
            'model': config.model_name,
            'messages': messages,
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
            'top_p': config.top_p,
            'presence_penalty': config.presence_penalty,
            'frequency_penalty': config.frequency_penalty,
            'stream': True,
            'stream_options': {'include_usage': True},
        }
        # # logger.info(f"Final payload keys: {list(payload.keys())}")
        # if 'tools' in payload:
        #     logger.info(f"Tools in payload: {json.dumps(payload['tools'], ensure_ascii=False)}")
        # if 'web_search' in payload:
        #     logger.info(f"web_search in payload: {json.dumps(payload['web_search'], ensure_ascii=False)}")
        if enable_tool_calls and tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        if enable_search:
            tool_list = model_cfg.get('web_search_tool', [{"type": "web_search", "web_search": {"enable": True}}])
            if tool_list:
                search_config = tool_list[0].get('web_search', {})
            else:
                search_config = {"enable": True}
            payload['web_search'] = search_config

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
        tool_calls_buffer = {}
        usage_info = None
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
                    # logger.info('DEBUG stream chunk: %s', json.dumps(data, ensure_ascii=False))
                    if 'usage' in data:
                        usage_info = data['usage']
                    choices = data.get('choices')
                    if not choices:
                        continue
                    delta = data['choices'][0]['delta']
                    content = delta.get('content', '')
                    if content:
                        full_content.append(content)
                        yield json.dumps({'content': content})
                    reasoning = delta.get('reasoning_content', '')
                    # 收集 tool_calls
                    if 'tool_calls' in delta:
                        # if 'tool_calls' in delta:
                            # logger.info(f"Received tool_calls delta: {json.dumps(delta['tool_calls'], ensure_ascii=False)}")
                        for tc_delta in delta['tool_calls']:
                            idx = tc_delta.get('index', 0)
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    'id': '',
                                    'type': 'function',
                                    'function': {'name': '', 'arguments': ''}
                                }
                            tc_acc = tool_calls_buffer[idx]
                            if 'id' in tc_delta and tc_delta['id']:
                                tc_acc['id'] = tc_delta['id']
                            if 'function' in tc_delta:
                                if 'name' in tc_delta['function'] and tc_delta['function']['name']:
                                    tc_acc['function']['name'] += tc_delta['function']['name']
                                if 'arguments' in tc_delta['function']:
                                    tc_acc['function']['arguments'] += tc_delta['function']['arguments']
                    if reasoning:
                        full_reasoning.append(reasoning)
                        yield json.dumps({'reasoning': reasoning})  # 向前端发送思考内容
                    if cache.get(stop_key):
                        update_task_status(task, 'failed', error='用户停止生成')
                        yield json.dumps({'stopped': True})
                        return
                except (json.JSONDecodeError, KeyError):
                    continue

        # assistant_content = ''.join(full_content)
        # assistant_reasoning = ''.join(full_reasoning)

        # Message.objects.create(
        #     conversation=conv,
        #     role='assistant',
        #     content=assistant_content,
        #     reasoning_content=assistant_reasoning,
        #     model_name=config.model_name,
        #     prompt_tokens=usage_info.get('prompt_tokens', 0),
        #     completion_tokens=usage_info.get('completion_tokens', 0),
        #     total_tokens=usage_info.get('total_tokens', 0)
        # )
        # update_task_status(task, 'completed')

        # if conv.title == '新对话':
        #     yield json.dumps({'need_title': True})
            # 整理收集到的 tool_calls
        full_content_str = ''.join(full_content)
        if not tool_calls_buffer and '||DSML||' in full_content_str:
            # logger.error('模型未按预期返回 tool_calls，而是输出了 DSML 文本，已阻止保存')
            update_task_status(task, 'failed', error='模型工具调用异常，请重试')
            yield json.dumps({'error': '工具调用失败，请重试或关闭高级功能'})
            return
        tool_calls = [v for k, v in sorted(tool_calls_buffer.items())]
        # logger.info('DEBUG final tool_calls_buffer: %s', json.dumps(tool_calls, ensure_ascii=False))
        # logger.info('DEBUG full_content: %s', ''.join(full_content))

        if tool_calls:
            # logger.info('DEBUG: tool_calls detected, executing tools...')
            # ------- 有工具调用 -------
            # 1. 将 assistant 消息（带 tool_calls）加入历史
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls
            })

            # 2. 执行每个工具，并将结果以 role=tool 追加
            for tc in tool_calls:
                func_name = tc['function']['name']
                try:
                    arguments = json.loads(tc['function']['arguments'])
                except (json.JSONDecodeError, KeyError):
                    arguments = {}
                try:
                    result = ToolManager.execute_tool(func_name, arguments)
                except Exception as e:
                    result = {"error": str(e)}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc['id'],
                    "content": json.dumps(result, ensure_ascii=False)
                })

            # 3. 第二次流式请求，不带 tools，让 LLM 基于工具结果生成最终回答
            second_payload = {
                'model': config.model_name,
                'messages': messages,
                'temperature': config.temperature,
                'max_tokens': config.max_tokens,
                'top_p': config.top_p,
                'presence_penalty': config.presence_penalty,
                'frequency_penalty': config.frequency_penalty,
                'stream': True,
                'stream_options': {'include_usage': True},
            }
            try:
                # logger.info('DEBUG: second_payload messages count: %d', len(messages))
                second_resp = requests.post(
                    f'{provider.base_url.rstrip("/")}/chat/completions',
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {provider.api_key}',
                    },
                    json=second_payload,
                    stream=True,
                    timeout=90
                )
                second_resp.raise_for_status()
            except Exception as e:
                update_task_status(task, 'failed', error=str(e))
                yield json.dumps({'error': f'工具调用后请求失败: {str(e)}'})
                return

            final_content = []
            second_usage = None
            for line in second_resp.iter_lines():
                if not line:
                    continue
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        if 'usage' in data:
                            second_usage = data['usage']
                        choices = data.get('choices')
                        if not choices:
                            continue
                        delta = choices[0]['delta']
                        content = delta.get('content', '')
                        if content:
                            final_content.append(content)
                            yield json.dumps({'content': content})
                        if cache.get(stop_key):
                            update_task_status(task, 'failed', error='用户停止生成')
                            yield json.dumps({'stopped': True})
                            return
                    except (json.JSONDecodeError, KeyError):
                        continue

            # 保存第二次生成的 assistant 消息
            final_assistant = ''.join(final_content)
            Message.objects.create(
                conversation=conv,
                role='assistant',
                content=final_assistant,
                model_name=config.model_name,
                prompt_tokens=second_usage.get('prompt_tokens', 0) if second_usage else 0,
                completion_tokens=second_usage.get('completion_tokens', 0) if second_usage else 0,
                total_tokens=second_usage.get('total_tokens', 0) if second_usage else 0
            )
            update_task_status(task, 'completed')
            if conv.title == '新对话':
                yield json.dumps({'need_title': True})
            return

        else:
            assistant_content = ''.join(full_content)
            assistant_reasoning = ''.join(full_reasoning)

            Message.objects.create(
                conversation=conv,
                role='assistant',
                content=assistant_content,
                reasoning_content=assistant_reasoning,
                model_name=config.model_name,
                prompt_tokens=usage_info.get('prompt_tokens', 0) if usage_info else 0,
                completion_tokens=usage_info.get('completion_tokens', 0) if usage_info else 0,
                total_tokens=usage_info.get('total_tokens', 0) if usage_info else 0
            )
            update_task_status(task, 'completed')

            if conv.title == '新对话':
                yield json.dumps({'need_title': True})
    finally:                                # <--- 新增
        conv.is_generating = False
        try:
            conv.save(update_fields=['is_generating'])
        except Exception:
            logger.exception('Failed to reset is_generating for conversation %s', conversation_id)






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
    logger.info(f"generate_title 开始: conv_id={conversation_id}, uid={uid}")
    try:
        conv = Conversation.objects.get(id=conversation_id, uid_id=uid, is_deleted=False)
    except Conversation.DoesNotExist:
        logger.warning(f"generate_title: 对话 {conversation_id} 不存在或不属于用户 {uid}")
        return False
    # 获取首条用户消息作为标题生成的素材
    first_msg = Message.objects.filter(conversation=conv, role='user').first()
    if not first_msg:
        logger.warning(f"generate_title: 对话 {conversation_id} 无用户消息")
        conv.title = "新对话"
        conv.save()
        return False
    # 使用简单方式生成标题（调用 LLM 取摘要）
    try:
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
            logger.info(f"generate_title: 请求生成标题，model={title_model}")
            resp = requests.post(
                f'{provider.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=15
            )
            resp.raise_for_status()
            raw_title = resp.json()['choices'][0]['message']['content'].strip().strip('"')
            if not raw_title:
                logger.warning("generate_title: 模型返回空标题，使用截断标题")
                title = first_msg.content[:10] + '...'
            else:
                title = raw_title
            logger.info(f"generate_title: 生成成功，标题='{title}'")
        except Exception as e:
            logger.error(f"generate_title: LLM 请求失败，使用截断标题。错误: {e}")
            title = first_msg.content[:10] + '...'
        conv.title = title
        conv.save()
        return title
    except Exception:
        conv.title = first_msg.content[:10] + '...'
        conv.save()
        logger.info(f"generate_title: 标题已保存为 '{title}'")
        return conv.title

# tool calls,函数名和配置表的name对应上
class InternalToolService:
    @ staticmethod
    def this_is_a_case():
        return {"isok":"true","msg":"test"}

    """
    @staticmethod
    def get_order_status(order_id: str) -> dict:
        # 实现你的业务逻辑
        return {"status": "shipped", "order_id": order_id}
    
    在工具表中的配置:
        ToolDefinition.objects.create(
        name='get_order_status',
        display_name='查询订单状态',
        description='根据订单号查询最新状态',
        parameters_schema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"}
            },
            "required": ["order_id"]
        },
        tool_type='internal'
    )
    """