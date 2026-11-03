"""apps/rag/services.py — 检索 / 拼 Prompt / 流式生成

D1（当前）：检索 = zhparser 全文检索 + 标题实体命中（双通道，不依赖外部 embedding）
D2（有 Qwen Key 后）：把 retrieval_mode 改成 hybrid，向量通道自动加入，用 RRF 融合
"""
import json
import logging
import re
import time

import requests
from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.db.models import F

from apps.llm_config.models import LLMProvider

from .models import RagChunk, RagPage, RagSetting
from .utils import image_url

logger = logging.getLogger(__name__)

# 复用连接：requests.post 每次都新建 TCP+TLS，冷启动实测能到 15 秒
_HTTP = requests.Session()

# 别名目标页的额外加权：别名是用户明确说出的映射，要压过字面巧合
ALIAS_BOOST = 0.6

DEFAULTS = {
    'rag.fts_config': 'zh',          # 没有 zh 配置时自动退回 simple
    'rag.top_k': '8',
    'rag.per_page': '3',
    'rag.retrieval_mode': 'fts',     # fts | hybrid
    'rag.llm_model': '',             # 空 = 用 provider 的第一个模型
    'rag.temperature': '0.1',
    'rag.max_tokens': '4000',
    'rag.question_max_len': '200',
    'rag.inflight_limit': '2',
    'rag.rate_per_min': '8',
    'rag.embedding.base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'rag.embedding.model': 'text-embedding-v4',
    'rag.embedding.dim': '1024',
    'rag.embedding.api_key': '',
    'rag.vector_weight': '1.8',
}

SYSTEM_PROMPT = """你是《星露谷物语》的中文资料助手，只根据下面提供的【资料】回答。

规则：
1. 只能使用【资料】里的事实，不要补充资料以外的设定、数值或攻略。
2. 每条事实后面标注来源编号，格式如 [1]、[2][3]，编号必须来自【资料】。
3. 数字、价格、日期、季节、人名必须与资料完全一致，不要换算或四舍五入。
4. 资料不足以回答时，说"我拿到的资料里没有相关内容"，并说明你查到了什么、缺什么，禁止猜测；不要说"Wiki 上没有"——本系统只收录了部分页面。
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
# 只丢高频虚词。zhparser 已经把 的/了/吗 这类标成 u 类型丢掉了，
# 这里补的是被映射成 v/n 但没检索价值的词
STOPWORDS = set(
    "的 是 有 会 在 和 与 或 我 你 他 她 它 这 那 了 吗 呢 吧 啊 呀 "
    "就 都 也 还 要 能 可以 什么 怎么 怎样 多少 哪些 哪个 如何 请问 一下"
    .split())


def _query_terms(question, cfg):
    """用数据库自己的 zhparser 分词，拿到真实 lexeme（Python 侧不瞎切中文）"""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT to_tsvector(%s::regconfig, %s)::text", [cfg, question])
            raw = cur.fetchone()[0] or ''
    except Exception as e:                                      # noqa: BLE001
        logger.warning('分词失败(config=%s)，退回 plain 查询: %s', cfg, e)
        return []
    terms, seen = [], set()
    for t in re.findall(r"'([^']+)'", raw):
        t = t.strip()
        if not t or t in seen or t in STOPWORDS:
            continue
        seen.add(t)                  # 单字也保留（鱼/金/矿 都有意义），只丢虚词
        terms.append(t)
    return terms[:24]


def _fts_hits(question, cfg, limit=40):
    """zhparser 全文检索。

    关键：不能用 plain（plainto_tsquery 是"所有词必须同时出现"，中文自然问句几乎必然 0 命中）。
    这里先用 DB 分词拿到 lexeme，再用 OR 拼 tsquery。
    """
    known = cache.get('rag:fts_config_ok')
    order = [known] if known else []
    for c in (cfg, 'simple'):
        if c not in order:
            order.append(c)
    for config in order:
        try:
            terms = _query_terms(question, config)
            if terms:
                safe = [re.sub(r"[&|!():*'\\]", '', t) for t in terms]
                safe = [t for t in safe if t]
                query = SearchQuery(' | '.join(safe), config=config, search_type='raw')
            else:
                query = SearchQuery(question, config=config, search_type='plain')
            qs = (
                RagChunk.objects.select_related('page')
                .annotate(rank=SearchRank(F('search_vector'), query))
                .filter(search_vector=query)
                .order_by('-rank')[:limit]
            )
            rows = [(c, float(c.rank or 0)) for c in qs]
            cache.set('rag:fts_config_ok', config, 600)
            return rows
        except Exception as e:                                  # noqa: BLE001
            logger.warning('FTS(config=%s) 失败: %s', config, e)
    return []


def _alias_map():
    """社区口语 → wiki 页面标题（存 rag_setting 的 rag.aliases，JSON）"""
    ck = 'rag:alias_map'
    m = cache.get(ck)
    if m is None:
        raw = get_setting('rag.aliases', '') or ''
        try:
            m = json.loads(raw) if raw.strip() else {}
        except Exception:                                      # noqa: BLE001
            logger.warning('rag.aliases 不是合法 JSON，忽略')
            m = {}
        cache.set(ck, m, 300)
    return m


def _expand_aliases(question):
    """把问句里的口语词追加成页面标题（不替换原词，保留字面覆盖率）"""
    m = _alias_map()
    if not m:
        return question, []
    extra, hits = [], []
    for alias in sorted(m, key=len, reverse=True):
        if len(alias) < 2 or alias not in question:
            continue
        target = (m.get(alias) or '').strip()
        if target and target not in question and target not in extra:
            extra.append(target)
            hits.append((alias, target))
    if not extra:
        return question, []
    return question + ' ' + ' '.join(extra), hits


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


def _q_chars(question):
    """把问题里的标点/空白全部去掉，只留中英文数字"""
    return re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]+", '', question or '')


def _literal_coverage(qc, text):
    """问题里的字，有多少比例**字面**出现在 text 里（长词优先，不重复计数）

    为什么不靠分词：zhparser 会把"几天成熟"切成"天成"+"熟"，而正文是"成熟"+"天"，
    词面上永远匹配不上。字面匹配绕开这个问题。
    """
    if not qc or not text:
        return 0.0
    covered = [False] * len(qc)
    for n in (4, 3, 2, 1):                       # 长词优先
        for i in range(len(qc) - n + 1):
            g = qc[i:i + n]
            if g in STOPWORDS:
                continue
            if g not in text:
                continue
            start = 0
            while True:
                p = qc.find(g, start)
                if p < 0:
                    break
                for k in range(p, p + n):
                    covered[k] = True
                start = p + 1
    return sum(covered) / len(qc)


def _lexemes(chunks):
    """取出这批 chunk 的 tsvector 词集，用于"问题里的词到底出现在哪一块"的精确打分"""
    ids = [c.pk for c in chunks]
    if not ids:
        return {}
    out = {}
    for cid, tv in RagChunk.objects.filter(pk__in=ids).values_list('id', 'search_vector'):
        out[cid] = set(re.findall(r"'([^']+)'", str(tv) or ''))
    return out


def _entity_fallback(question, pids, per_page=2):
    """命名的页面一条都没被 FTS 命中时的兜底：只给前两块，低分（不抢 FTS 的位置）"""
    out = []
    for pid in pids:
        for i, c in enumerate(
                RagChunk.objects.select_related('page')
                        .filter(page_id=pid).order_by('chunk_index')[:per_page]):
            out.append((c, 0.30 - 0.05 * i))
    return out


def _merge(scored):
    """同一 chunk 取最高分，避免重复"""
    best = {}
    for c, s in scored:
        if c.pk not in best or best[c.pk][1] < s:
            best[c.pk] = (c, s)
    return sorted(best.values(), key=lambda x: -x[1])


def retrieve(question, top_k=None, per_page=None):
    """返回 [{...}]，已按分数排序、按页面去重"""
    top_k = top_k or get_int('rag.top_k', 8)
    per_page = per_page or get_int('rag.per_page', 3)
    cfg = get_setting('rag.fts_config', 'zh')

    question, alias_hits = _expand_aliases(question)
    alias_pids = set()
    if alias_hits:
        alias_pids = set(RagPage.objects.filter(
            title__in=[t for _, t in alias_hits]).values_list('page_id', flat=True))
        logger.info('别名命中: %s → 页面 %s', alias_hits, alias_pids)
    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)
    scored = _fts_hits(question, cfg, limit=60)

    # 命名实体的页面，整页 chunk 无条件进候选池。
    # 不能指望 ts_rank 把它排进前 60：短块词密度高，infobox 常被挤到 60 名外
    pool_pids = pids | alias_pids
    if pool_pids:
        have = {c.pk for c, _ in scored}
        extra = (RagChunk.objects.select_related('page')
                 .filter(page_id__in=pool_pids).order_by('chunk_index')[:80])
        scored += [(c, 0.0) for c in extra if c.pk not in have]

    # 按"问题里的词覆盖了几成 + 是否出现在章节名 + ts_rank"重新打分。
    # 不能只用 ts_rank：每块都带标题前缀，短块词密度高会误赢（问"多少钱"返回"食谱"就是这么来的）
    qc = _q_chars(question)
    if scored and qc:
        rescored = []
        for c, rank in scored:
            cover = _literal_coverage(qc, c.content or '')
            head = 0.25 if _literal_coverage(qc, c.header_path or '') > 0.34 else 0.0
            rescored.append((c, cover + head + 0.3 * min(1.0, rank)))
        scored = rescored

    # 实体页轻加权（+0.25，不能再给 1.5 —— 那会把向量捞上来的正确块挤掉）
    if pids:
        scored = [(c, s + (0.25 if c.page_id in pids else 0.0)) for c, s in scored]
        hit_pages = {c.page_id for c, _ in scored}
        scored += _entity_fallback(question, pool_pids - hit_pages)

    if get_setting('rag.retrieval_mode', 'fts') == 'hybrid':
        try:
            from .embedding import search_by_vector
            vec = search_by_vector(question, limit=40)
            if pids:
                vec = [(c, sc + (0.25 if c.page_id in pids else 0.0)) for c, sc in vec]
            scored += vec
        except Exception as e:                                  # noqa: BLE001
            logger.warning('向量通道不可用，退回纯关键词检索: %s', e)

    # 别名目标页额外加权：必须放在向量合并之后，否则向量捞上来的块不带这个分
    if alias_pids:
        scored = [(c, s + (ALIAS_BOOST if c.page_id in alias_pids else 0.0)) for c, s in scored]

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
