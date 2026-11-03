# -*- coding: utf-8 -*-
"""修复 RAG 检索层两个 bug：_fts_hits 改 OR 查询、实体命中不再固定塞前 3 块"""
import shutil

P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()

if '_query_terms' in s and '_entity_fallback' in s:
    print('[SKIP] 检索层已经是新版，没有改动')
    raise SystemExit(0)

if '\nimport re\n' not in s:
    s = s.replace('import json\nimport logging', 'import json\nimport logging\nimport re', 1)
if 'from django.db import close_old_connections, connection' not in s:
    s = s.replace('from django.db import close_old_connections',
                  'from django.db import close_old_connections, connection', 1)

assert 'def _fts_hits(' in s, '[FAIL] 找不到 _fts_hits'
assert 'def _all_pages(' in s, '[FAIL] 找不到 _all_pages'
head, tail = s[:s.index('def _fts_hits(')], s[s.index('def _all_pages('):]

new_fts = '''# 只丢高频虚词。zhparser 已经把 的/了/吗 这类标成 u 类型丢掉了，
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
                safe = [re.sub(r"[&|!():*'\\\\]", '', t) for t in terms]
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


'''
s = head + new_fts + tail

assert 'def _entity_hits(' in s, '[FAIL] 找不到 _entity_hits'
assert 'def _merge(' in s, '[FAIL] 找不到 _merge'
head, tail = s[:s.index('def _entity_hits(')], s[s.index('def _merge('):]
new_ent = '''def _entity_fallback(question, pids, per_page=2):
    """命名的页面一条都没被 FTS 命中时的兜底：只给前两块，低分（不抢 FTS 的位置）"""
    out = []
    for pid in pids:
        for i, c in enumerate(
                RagChunk.objects.select_related('page')
                        .filter(page_id=pid).order_by('chunk_index')[:per_page]):
            out.append((c, 0.30 - 0.05 * i))
    return out


'''
s = head + new_ent + tail

if 'def _title_bonus(' in s:
    a = s.index('def _title_bonus(')
    b = s.index('def retrieve(', a)
    s = s[:a] + s[b:]

old_body = """    scored = _fts_hits(question, cfg)
    if scored:
        scored = [(c, s + _title_bonus(question, c)) for c, s in scored]
    scored += _entity_hits(question)
"""
new_body = """    pids = set(_entity_titles(question))
    scored = _fts_hits(question, cfg)

    # 归一到 0~1，让全文分 / 实体加权 / 向量分三者可比
    if scored:
        mx = max(s for _, s in scored) or 1.0
        scored = [(c, min(1.0, s / mx)) for c, s in scored]

    # 实体页加权 +0.6（不再固定塞前 3 块，块由全文检索决定）
    if pids:
        scored = [(c, s + (0.6 if c.page_id in pids else 0.0)) for c, s in scored]
        hit_pages = {c.page_id for c, _ in scored}
        scored += _entity_fallback(question, pids - hit_pages)
"""
assert old_body in s, '[FAIL] retrieve 排序段锚点不匹配'
s = s.replace(old_body, new_body, 1)

shutil.copy(P, P + '.bak')
open(P, 'w', encoding='utf-8').write(s)

print('[OK] 已修复检索层')
print('[CHECK] _query_terms        :', '_query_terms' in s)
print('[CHECK] search_type=raw     :', "search_type='raw'" in s)
print('[CHECK] _entity_hits 已移除  :', '_entity_hits' not in s)
print('[CHECK] _title_bonus 已移除  :', '_title_bonus' not in s)
print('[CHECK] 备份 :', P + '.bak')
print('[CHECK] 行数 :', len(s.splitlines()), '(399 或 401)')
