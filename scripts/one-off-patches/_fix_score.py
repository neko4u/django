# -*- coding: utf-8 -*-
"""把检索排序从 ts_rank 改成"词覆盖率"打分；实体加权 1.5 → 0.25"""
P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()

if 'def _lexemes(' in s:
    print('[SKIP] 已经是词覆盖率版本')
    raise SystemExit(0)

anchor = 'def _entity_fallback('
add = '''def _lexemes(chunks):
    """取出这批 chunk 的 tsvector 词集，用于"问题里的词到底出现在哪一块"的精确打分"""
    ids = [c.pk for c in chunks]
    if not ids:
        return {}
    out = {}
    for cid, tv in RagChunk.objects.filter(pk__in=ids).values_list('id', 'search_vector'):
        out[cid] = set(re.findall(r"'([^']+)'", str(tv) or ''))
    return out


'''
assert anchor in s, '[FAIL] 找不到 _entity_fallback'
s = s.replace(anchor, add + anchor, 1)

old = """    pids = set(_entity_titles(question))
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
new = """    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)
    scored = _fts_hits(question, cfg, limit=60)

    # 按"问题里的词覆盖了几成 + 是否出现在章节名 + ts_rank"重新打分。
    # 不能只用 ts_rank：每块都带标题前缀，短块词密度高会误赢（问"多少钱"返回"食谱"就是这么来的）
    if scored and terms:
        tvmap = _lexemes([c for c, _ in scored])
        rescored = []
        n = len(terms)
        for c, rank in scored:
            tv = tvmap.get(c.pk) or set()
            cover = sum(1 for t in terms if t in tv) / n
            head = 0.25 if any(t in (c.header_path or '') for t in terms) else 0.0
            rescored.append((c, cover + head + 0.3 * min(1.0, rank)))
        scored = rescored

    # 实体页轻加权（+0.25，不能再给 1.5 —— 那会把向量捞上来的正确块挤掉）
    if pids:
        scored = [(c, s + (0.25 if c.page_id in pids else 0.0)) for c, s in scored]
        hit_pages = {c.page_id for c, _ in scored}
        scored += _entity_fallback(question, pids - hit_pages)
"""
assert old in s, '[FAIL] retrieve 排序段锚点不匹配'
s = s.replace(old, new, 1)

old2 = """            from .embedding import search_by_vector
            scored += search_by_vector(question, limit=40)"""
new2 = """            from .embedding import search_by_vector
            vec = search_by_vector(question, limit=40)
            if pids:
                vec = [(c, sc + (0.25 if c.page_id in pids else 0.0)) for c, sc in vec]
            scored += vec"""
assert old2 in s, '[FAIL] 向量段锚点不匹配'
s = s.replace(old2, new2, 1)

open(P, 'w', encoding='utf-8').write(s)
print('[OK] 已改用词覆盖率打分')
print('[CHECK] _lexemes        :', 'def _lexemes(' in s)
print('[CHECK] 实体加权 0.25   :', '+ (0.25 if c.page_id in pos' in s or '+ (0.25 if c.page_id in pids' in s)
print('[CHECK] limit=60        :', 'limit=60' in s)
print('[CHECK] 行数            :', len(s.splitlines()), '(422 或 424)')
