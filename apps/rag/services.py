"""apps/rag/services.py — 检索 / 拼 Prompt / 流式生成

D1（当前）：检索 = zhparser 全文检索 + 标题实体命中（双通道，不依赖外部 embedding）
D2（有 Qwen Key 后）：把 retrieval_mode 改成 hybrid，向量通道自动加入，用 RRF 融合
"""
import json
import logging
import time

import requests
from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import F

from apps.llm_config.models import LLMProvider

from .models import RagChunk, RagPage, RagSetting
from .utils import image_url

logger = logging.getLogger(__name__)

DEFAULTS = {
    'rag.fts_config': 'zh',          # 没有 zh 配置时自动退回 simple
    'rag.top_k': '8',
    'rag.per_page': '3',
    'rag.retrieval_mode': 'fts',     # fts | hybrid
    'rag.llm_model': '',             # 空 = 用 provider 的第一个模型
    'rag.temperature': '0.1',
    'rag.max_tokens': '1500',
    'rag.question_max_len': '200',
    'rag.inflight_limit': '2',
    'rag.rate_per_min': '8',
    'rag.embedding.base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'rag.embedding.model': 'text-embedding-v4',
    'rag.embedding.dim': '1024',
    'rag.embedding.api_key': '',
}

SYSTEM_PROMPT = """你是《星露谷物语》的中文资料助手，只根据下面提供的【资料】回答。

规则：
1. 只能使用【资料】里的事实，不要补充资料以外的设定、数值或攻略。
2. 每条事实后面标注来源编号，格式如 [1]、[2][3]，编号必须来自【资料】。
3. 数字、价格、日期、季节、人名必须与资料完全一致，不要换算或四舍五入。
4. 资料不足以回答时，直接说"Wiki 里没有找到相关内容"，并说明你查到了什么、缺什么，禁止猜测。
5. 用简体中文回答，条理清晰；涉及多个物品/选项时用列表或表格。
6. 不要输出【资料】以外的网址，也不要提及"资料"这个词本身。"""


# --------------------------------------------------------------------------- 配置
def _from_settings(key):
    """rag.embedding.* 优先从 settings.RAG_EMBEDDING 读（/opt/config/django/project1settings.json）"""
    short = key.split('.')[-1]
    cfg = getattr(settings, 'RAG_EMBEDDING', None) or {}
    val = cfg.get(short)
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    return str(val).strip()


def get_setting(key, default=None):
    if key.startswith('rag.embedding.'):
        v = _from_settings(key)
        if v is not None:
            return v
    ck = 'rag:setting:' + key
    val = cache.get(ck)
    if val is None:
        try:
            val = RagSetting.objects.get(pk=key).value
        except RagSetting.DoesNotExist:
            val = DEFAULTS.get(key, default if default is not None else '')
        cache.set(ck, val, 60)
    return val


def get_int(key, fallback=0):
    try:
        return int(get_setting(key, str(fallback)))
    except (TypeError, ValueError):
        return fallback


def get_float(key, fallback=0.0):
    try:
        return float(get_setting(key, str(fallback)))
    except (TypeError, ValueError):
        return fallback


def clear_setting_cache():
    for k in list(DEFAULTS):
        cache.delete('rag:setting:' + k)
    cache.delete('rag:titles')


# --------------------------------------------------------------------------- 检索
def _fts_hits(question, cfg, limit=40):
    """zhparser 全文检索；配置不存在时自动降级 simple，并记住能用的那个"""
    known = cache.get('rag:fts_config_ok')
    order = [known] if known else []
    for c in (cfg, 'simple'):
        if c not in order:
            order.append(c)
    for config in order:
        try:
            q = SearchQuery(question, config=config, search_type='plain')
            qs = (
                RagChunk.objects.select_related('page')
                .annotate(rank=SearchRank(F('search_vector'), q))
                .filter(search_vector=q)
                .order_by('-rank')[:limit]
            )
            rows = [(c, float(c.rank or 0)) for c in qs]
            cache.set('rag:fts_config_ok', config, 600)
            return rows
        except Exception as e:                                  # noqa: BLE001
            logger.warning('FTS(config=%s) 失败: %s', config, e)
    return []


def _all_pages():
    key = 'rag:titles'
    data = cache.get(key)
    if data is None:
        data = list(RagPage.objects.values_list('page_id', 'title'))
        cache.set(key, data, 3600)
    return data


def _entity_titles(question, max_hits=4):
    """问题里出现的页面标题（实体链接）——中文分词切坏的兜底，也是精确查询的主力"""
    hits = []
    for pid, title in _all_pages():
        if len(title) >= 2 and title in question:
            hits.append((len(title), pid, title))
    hits.sort(reverse=True)
    out, used = [], set()
    for _, pid, title in hits:
        if pid in used:
            continue
        # 已有更长的标题覆盖它（防风草种子 命中时不要再取 防风草）
        if any(title in t and title != t for _, _, t in out):
            continue
        used.add(pid)
        out.append((len(title), pid, title))
        if len(out) >= max_hits:
            break
    return [pid for _, pid, _ in out]


def _entity_hits(question, per_page=3):
    out = []
    for pid in _entity_titles(question):
        chunks = list(
            RagChunk.objects.select_related('page').filter(page_id=pid).order_by('chunk_index')[:per_page]
        )
        for i, c in enumerate(chunks):
            out.append((c, 1.5 - 0.1 * i))     # 实体命中权重高于普通全文命中
    return out


def _merge(scored):
    """同一 chunk 取最高分，避免重复"""
    best = {}
    for c, s in scored:
        if c.pk not in best or best[c.pk][1] < s:
            best[c.pk] = (c, s)
    return sorted(best.values(), key=lambda x: -x[1])


def _title_bonus(question, chunk):
    t = chunk.page.title
    if len(t) >= 2 and t in question:
        return 0.8
    return 0.0


def retrieve(question, top_k=None, per_page=None):
    """返回 [{...}]，已按分数排序、按页面去重"""
    top_k = top_k or get_int('rag.top_k', 8)
    per_page = per_page or get_int('rag.per_page', 3)
    cfg = get_setting('rag.fts_config', 'zh')

    scored = _fts_hits(question, cfg)
    if scored:
        scored = [(c, s + _title_bonus(question, c)) for c, s in scored]
    scored += _entity_hits(question)

    if get_setting('rag.retrieval_mode', 'fts') == 'hybrid':
        try:
            from .embedding import search_by_vector
            scored += search_by_vector(question, limit=40)
        except Exception as e:                                  # noqa: BLE001
            logger.warning('向量通道不可用，退回纯关键词检索: %s', e)

    merged = _merge(scored)

    # 同一页面最多 per_page 条，避免整页霸屏
    per_count, out = {}, []
    for c, s in merged:
        pid = c.page_id
        if per_count.get(pid, 0) >= per_page:
            continue
        per_count[pid] = per_count.get(pid, 0) + 1
        out.append({
            'chunk_id': c.pk,
            'chunk_uid': f'{c.page_id}:{c.chunk_index}',
            'page_id': pid,
            'title': c.page.title,
            'header_path': c.header_path,
            'content': c.content,
            'content_type': c.content_type,
            'images': [image_url(n) for n in (c.images or [])][:6],
            'score': round(float(s), 4),
            'wiki_url': c.page.wiki_url,
            'updated_raw': c.page.updated_raw,
        })
        if len(out) >= top_k:
            break
    return out


# --------------------------------------------------------------------------- Prompt
def build_messages(question, hits):
    if not hits:
        return None
    blocks = []
    for i, h in enumerate(hits, 1):
        head = f'[资料{i}] {h["title"]}'
        if h['header_path'] and h['header_path'] != h['title']:
            head += f' > {h["header_path"].replace(h["title"] + " > ", "")}'
        blocks.append(f'{head}\n{h["content"]}')
    user = '【资料】\n' + '\n\n'.join(blocks) + f'\n\n【问题】{question}'
    return [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user},
    ]


def build_citations(hits):
    """前端引用卡片的数据（编号与 [n] 一一对应）"""
    out = []
    for i, h in enumerate(hits, 1):
        out.append({
            'index': i,
            'title': h['title'],
            'header_path': h['header_path'],
            'type': h['content_type'],
            'image': h['images'][0] if h['images'] else '',
            'images': h['images'][:3],
            'wiki_url': h['wiki_url'],
            'updated_raw': h['updated_raw'],
            'snippet': h['content'][:160],
        })
    return out


# --------------------------------------------------------------------------- 生成
def _get_provider():
    model = (get_setting('rag.llm_model') or '').strip()
    if model:
        for p in LLMProvider.objects.filter(is_active=True):
            if model in (p.model_list or []):
                return p, model
    p = LLMProvider.objects.filter(is_active=True, is_default=True).first() \
        or LLMProvider.objects.filter(is_active=True).order_by('id').first()
    if not p:
        raise RuntimeError('数据库里没有可用的 LLM Provider（llm_provider 表）')
    models = p.model_list or []
    return p, (models[0] if models else 'deepseek-chat')


def stream_completion(messages, model=None):
    """逐段产出 {'delta': '...'}；结束产出 {'usage': {...}}"""
    provider, default_model = _get_provider()
    model = model or default_model
    payload = {
        'model': model,
        'messages': messages,
        'stream': True,
        'temperature': get_float('rag.temperature', 0.1),
        'max_tokens': get_int('rag.max_tokens', 1500),
        'stream_options': {'include_usage': True},
    }
    url = provider.base_url.rstrip('/') + '/chat/completions'
    resp = requests.post(
        url,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {provider.api_key}'},
        json=payload,
        stream=True,
        timeout=(10, 120),
    )
    if resp.status_code >= 400:
        body = resp.text[:300]
        raise RuntimeError(f'LLM 接口返回 {resp.status_code}: {body}')

    usage = {}
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
        delta = choices[0].get('delta') or {}
        text = delta.get('content') or ''
        if text:
            yield {'delta': text}
    yield {'usage': usage, 'model_name': model}


# --------------------------------------------------------------------------- 限流 / 并发
def acquire_slot():
    """全局并发闸门：gunicorn 只有 3 个 worker，一条 SSE 会占死一个"""
    limit = get_int('rag.inflight_limit', 2)
    try:
        cache.add('rag:inflight', 0, 600)
        n = cache.incr('rag:inflight')
    except Exception:                                          # noqa: BLE001
        return True
    if n > limit:
        release_slot()
        return False
    return True


def release_slot():
    try:
        if cache.get('rag:inflight', 0) > 0:
            cache.decr('rag:inflight')
    except Exception:                                          # noqa: BLE001
        pass


def check_rate(uid):
    """单用户每分钟提问上限"""
    limit = get_int('rag.rate_per_min', 8)
    key = f'rag:rate:{uid}'
    try:
        if cache.add(key, 1, 60):
            return True
        n = cache.incr(key)
        return n <= limit
    except Exception:                                          # noqa: BLE001
        return True
