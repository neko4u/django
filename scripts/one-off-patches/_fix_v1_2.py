# -*- coding: utf-8 -*-
"""v1.2: max_tokens 4000 / Session 复用 + 查询向量缓存 / 空答案兜底 + 措辞修正
三个文件全部在内存改完才落盘；幂等，跑第二次是 0 改动。
"""
import io
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else '/opt/projects/project1'
S = BASE + '/apps/rag/services.py'
E = BASE + '/apps/rag/embedding.py'
V = BASE + '/apps/rag/views.py'

svc = io.open(S, encoding='utf-8').read()
emb = io.open(E, encoding='utf-8').read()
viw = io.open(V, encoding='utf-8').read()
changed = []

# ---------------- services.py ----------------
if '_HTTP = requests.Session()' not in svc:
    old = "logger = logging.getLogger(__name__)"
    assert old in svc, '[FAIL] services: logger 锚点'
    svc = svc.replace(old, old + "\n\n# 复用连接：requests.post 每次都新建 TCP+TLS，冷启动实测能到 15 秒\n_HTTP = requests.Session()", 1)
    changed.append('services: Session')

if "'rag.max_tokens': '1500'" in svc:
    svc = svc.replace("'rag.max_tokens': '1500'", "'rag.max_tokens': '4000'", 1)
    changed.append('services: max_tokens 1500→4000')

old_p = '4. 资料不足以回答时，直接说"Wiki 里没有找到相关内容"，并说明你查到了什么、缺什么，禁止猜测。'
new_p = ('4. 资料不足以回答时，说"我拿到的资料里没有相关内容"，并说明你查到了什么、缺什么，禁止猜测；'
         '不要说"Wiki 上没有"——本系统只收录了部分页面。')
if old_p in svc:
    svc = svc.replace(old_p, new_p, 1)
    changed.append('services: prompt 措辞')

if 'reasoning_chars' not in svc:
    a = svc.index('def stream_completion(')
    b = svc.index('# --------------------------------------------------------------------------- 限流 / 并发')
    new_stream = '''def stream_completion(messages, model=None):
    """逐段产出 {'delta': '...'}；结束产出 usage / finish_reason / reasoning_chars

    推理模型会把 token 先花在 reasoning_content 上，max_tokens 太小时正文可能是空的
    （前端表现为"没有收到任何内容"），所以必须把 reasoning_chars 和 finish_reason 报上去。
    """
    provider, default_model = _get_provider()
    model = model or default_model
    payload = {
        'model': model,
        'messages': messages,
        'stream': True,
        'temperature': get_float('rag.temperature', 0.1),
        'max_tokens': get_int('rag.max_tokens', 4000),
        'stream_options': {'include_usage': True},
    }
    url = provider.base_url.rstrip('/') + '/chat/completions'
    resp = _HTTP.post(
        url,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {provider.api_key}'},
        json=payload,
        stream=True,
        timeout=(10, 180),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'LLM 接口返回 {resp.status_code}: {resp.text[:300]}')

    usage = {}
    reasoning_chars = 0
    finish_reason = ''
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode('utf-8', 'ignore').strip()
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            break
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if obj.get('usage'):
            usage = obj['usage']
        choices = obj.get('choices') or []
        if not choices:
            continue
        ch = choices[0]
        finish_reason = ch.get('finish_reason') or finish_reason
        delta = ch.get('delta') or {}
        if delta.get('reasoning_content'):
            reasoning_chars += len(delta['reasoning_content'])
        text = delta.get('content') or ''
        if text:
            yield {'delta': text}
    yield {
        'usage': usage,
        'model_name': model,
        'finish_reason': finish_reason,
        'reasoning_chars': reasoning_chars,
    }


'''
    svc = svc[:a] + new_stream + svc[b:]
    changed.append('services: stream_completion 重写')

# ---------------- embedding.py ----------------
if 'import hashlib' not in emb:
    emb = emb.replace('import json\nimport logging', 'import hashlib\nimport json\nimport logging', 1)
    changed.append('embedding: import hashlib')

if 'from django.core.cache import cache' not in emb:
    if 'from .services import get_float, get_int, get_setting' in emb:
        emb = emb.replace('from .services import get_float, get_int, get_setting',
                          'from django.core.cache import cache\n\nfrom .services import get_float, get_int, get_setting', 1)
    elif 'from .services import get_int, get_setting' in emb:
        emb = emb.replace('from .services import get_int, get_setting',
                          'from django.core.cache import cache\n\nfrom .services import get_float, get_int, get_setting', 1)
    else:
        raise SystemExit('[FAIL] embedding: 两种 services 导入写法都不匹配')
    changed.append('embedding: cache 导入')

if '_HTTP = requests.Session()' not in emb:
    assert 'BATCH_DEFAULT = 10' in emb, '[FAIL] embedding: BATCH_DEFAULT 锚点'
    emb = emb.replace('BATCH_DEFAULT = 10',
                      '_HTTP = requests.Session()   # 复用连接，省掉每次提问的 TCP+TLS\n\nBATCH_DEFAULT = 10', 1)
    changed.append('embedding: Session')

if 'def embed_query(' not in emb:
    assert 'def probe(' in emb, '[FAIL] embedding: def probe 锚点'
    emb = emb.replace('def probe(', '''def embed_query(text, dim=None):
    """查询向量带 Redis 缓存：同一个问题重复提问不再调 API（省约 270ms）"""
    dim = int(dim or get_int('rag.embedding.dim', 1024))
    ck = 'rag:qvec:%d:%s' % (dim, hashlib.md5((text or '').encode('utf-8')).hexdigest()[:16])
    hit = cache.get(ck)
    if hit:
        return hit
    vec = embed_batch([text], dim=dim)[0]
    try:
        cache.set(ck, vec, 3600)
    except Exception:                                          # noqa: BLE001
        pass
    return vec


def probe(''', 1)
    changed.append('embedding: embed_query')

if '    vec = embed_batch([question], dim=dim)[0]' in emb:
    emb = emb.replace('    vec = embed_batch([question], dim=dim)[0]',
                      '    vec = embed_query(question, dim=dim)', 1)
    changed.append('embedding: search_by_vector 走缓存')

if 'resp = requests.post(_endpoint()' in emb:
    emb = emb.replace('resp = requests.post(_endpoint()', 'resp = _HTTP.post(_endpoint()', 1)
    changed.append('embedding: embed_batch 用 Session')

# ---------------- views.py ----------------
if "'没有在 Wiki 里检索到与「{q}」相关的内容。" in viw:
    viw = viw.replace("'没有在 Wiki 里检索到与「{q}」相关的内容。",
                      "'我收录的资料里没有检索到与「{q}」相关的内容。", 1)
    changed.append('views: NO_HIT_TIP 首句')

old_tail = "    '（部分 Wiki 页面目前抓取不到，正在等站点后端恢复）'\n)"
new_tail = ("    '说明：本系统只收录了官方 Wiki 的 74%（1,511 / 2,078 页），'\n"
            "    '缺的 500 多页是站点后端故障期间抓不到的（例如「传说之鱼」就没收录）。'\n"
            "    '这不是 Wiki 没有，而是我们没抓到。'\n)")
if old_tail in viw:
    viw = viw.replace(old_tail, new_tail, 1)
    changed.append('views: NO_HIT_TIP 说明段')

if 'finish_reason' not in viw:
    old_init = "        usage = {}\n        model_name = ''\n        hits = []"
    assert old_init in viw, '[FAIL] views: 初始化锚点'
    viw = viw.replace(old_init, "        usage = {}\n        model_name = ''\n        finish_reason = ''\n        reasoning_chars = 0\n        hits = []", 1)
    changed.append('views: 初始化 finish_reason')

old_loop = """                    elif 'usage' in ev:
                        usage = ev.get('usage') or {}
                        model_name = ev.get('model_name', '')"""
new_loop = """                    elif 'usage' in ev:
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
                    yield sse({'type': 'delta', 'text': tip})"""
if '模型写了' in viw:
    pass
elif old_loop in viw:
    viw = viw.replace(old_loop, new_loop, 1)
    changed.append('views: 空答案兜底')
else:
    raise SystemExit('[FAIL] views: stream 循环锚点不匹配（未写入任何文件）')

# ---------------- 一次性落盘 ----------------
if changed:
    io.open(S, 'w', encoding='utf-8').write(svc)
    io.open(E, 'w', encoding='utf-8').write(emb)
    io.open(V, 'w', encoding='utf-8').write(viw)

print('[OK] 改动 %d 处：' % len(changed))
for c in changed:
    print('   -', c)
print()
for name, path in (('services.py', S), ('embedding.py', E), ('views.py', V)):
    print('   %-14s %d 行' % (name, len(io.open(path, encoding='utf-8').read().splitlines())))
