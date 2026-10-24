"""apps/rag/views.py — Wiki 问答页 + SSE 接口"""
import json
import logging
import time

from django.db import close_old_connections
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from apps.login.decorators import login_required_api, login_required_view

from . import services
from .models import RagQueryLog
from .utils import client_ip, sse

logger = logging.getLogger(__name__)

NO_HIT_TIP = (
    '我收录的资料里没有检索到与「{q}」相关的内容。\n\n'
    '可以试试：\n'
    '- 换成具体的物品/人物/地点名，例如「防风草」「艾芙琳」「Joja超市」\n'
    '- 问得更具体一点，例如「防风草多少钱」「春天的作物有哪些」\n\n'
    '说明：本系统只收录了官方 Wiki 的 74%（1,511 / 2,078 页），'
    '缺的 500 多页是站点后端故障期间抓不到的（例如「传说之鱼」就没收录）。'
    '这不是 Wiki 没有，而是我们没抓到。'
)


@login_required_view
def wiki_page(request):
    return render(request, 'rag/ask.html')


@csrf_exempt
@login_required_api
def ask_stream(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '只接受 POST'}, status=405)

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:                                          # noqa: BLE001
        return JsonResponse({'status': 'error', 'message': '请求体不是合法 JSON'}, status=400)

    question = (body.get('question') or '').strip()
    max_len = services.get_int('rag.question_max_len', 200)
    if not question:
        return JsonResponse({'status': 'error', 'message': '问题不能为空'}, status=400)
    if len(question) > max_len:
        return JsonResponse({'status': 'error', 'message': f'问题最多 {max_len} 个字'}, status=400)

    uid = request.session['info']['uid']
    if not services.check_rate(uid):
        return JsonResponse(
            {'status': 'error', 'message': '提问太频繁了，休息一分钟再来吧'}, status=429
        )
    if not services.acquire_slot():
        return JsonResponse(
            {'status': 'error', 'message': '正在回答其他人的问题，请稍等几秒再试'}, status=429
        )

    def event_stream():
        close_old_connections()
        t0 = time.time()
        first_token_ms = 0
        parts = []
        usage = {}
        model_name = ''
        finish_reason = ''
        reasoning_chars = 0
        hits = []
        error = ''
        try:
            hits = services.retrieve(question)
            yield sse({
                'type': 'meta',
                'citations': services.build_citations(hits),
                'hit_count': len(hits),
                'mode': services.get_setting('rag.retrieval_mode', 'fts'),
            })

            if not hits:
                text = NO_HIT_TIP.format(q=question)
                parts.append(text)
                yield sse({'type': 'delta', 'text': text})
            else:
                messages = services.build_messages(question, hits)
                for ev in services.stream_completion(messages):
                    if 'delta' in ev:
                        if not first_token_ms:
                            first_token_ms = int((time.time() - t0) * 1000)
                        parts.append(ev['delta'])
                        yield sse({'type': 'delta', 'text': ev['delta']})
                    elif 'usage' in ev:
                        usage = ev.get('usage') or {}
                        model_name = ev.get('model_name', '')
                        finish_reason = ev.get('finish_reason') or ''
                        reasoning_chars = int(ev.get('reasoning_chars') or 0)

                # 模型把 token 全花在思考上 / 被截断 → 明确告诉用户，不要静默返回空
                if not parts:
                    if finish_reason == 'length':
                        why = '回答被长度上限截断'
                    elif reasoning_chars:
                        why = '模型写了 %d 字思考，把上限用完了，没留给正文' % reasoning_chars
                    else:
                        why = '模型返回了空内容'
                    tip = '（%s，没能生成答案。请把问题问得更具体一些，或稍后重试。）' % why
                    parts.append(tip)
                    yield sse({'type': 'delta', 'text': tip})
        except Exception as e:                                 # noqa: BLE001
            error = f'{type(e).__name__}: {e}'
            logger.exception('RAG 生成失败')
            yield sse({'type': 'error', 'message': '生成失败了，请稍后重试（错误已记录）'})
        finally:
            services.release_slot()
            log_id, latency = 0, int((time.time() - t0) * 1000)
            try:
                answer = ''.join(parts)
                log = RagQueryLog.objects.create(
                    uid=uid,
                    question=question,
                    answer=answer,
                    mode=services.get_setting('rag.retrieval_mode', 'fts'),
                    top_chunks=[{'uid': h['chunk_uid'], 'title': h['title'], 'score': h['score']}
                                for h in hits],
                    hit_count=len(hits),
                    latency_ms=latency,
                    first_token_ms=first_token_ms,
                    model_name=model_name,
                    prompt_tokens=int(usage.get('prompt_tokens') or 0),
                    completion_tokens=int(usage.get('completion_tokens') or 0),
                    total_tokens=int(usage.get('total_tokens') or 0),
                    error=error[:2000],
                )
                log_id = log.id
            except Exception:                                   # noqa: BLE001
                logger.exception('写 RagQueryLog 失败')
            close_old_connections()
            yield sse({'type': 'done', 'log_id': log_id,
                       'latency_ms': latency, 'first_token_ms': first_token_ms})

    resp = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    return resp


@csrf_exempt
@login_required_api
def feedback(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '只接受 POST'}, status=405)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
        log_id = int(body.get('log_id') or 0)
        value = int(body.get('value') or 0)
    except Exception:                                          # noqa: BLE001
        return JsonResponse({'status': 'error', 'message': '参数错误'}, status=400)
    if value not in (-1, 0, 1):
        return JsonResponse({'status': 'error', 'message': 'value 只能是 -1/0/1'}, status=400)
    uid = request.session['info']['uid']
    n = RagQueryLog.objects.filter(id=log_id, uid=uid).update(feedback=value)
    return JsonResponse({'status': 'ok' if n else 'error', 'updated': n})
