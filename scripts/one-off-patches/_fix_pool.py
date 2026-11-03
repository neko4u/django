# -*- coding: utf-8 -*-
"""命名实体的整页 chunk 无条件进候选池（ts_rank 会把 infobox 挤出前 60）"""
P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()

if '整页 chunk 都进候选池' in s:
    print('[SKIP] 已经有这段逻辑')
    raise SystemExit(0)

old = """    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)
    scored = _fts_hits(question, cfg, limit=60)
"""
new = """    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)
    scored = _fts_hits(question, cfg, limit=60)

    # 命名实体的页面，整页 chunk 无条件进候选池。
    # 不能指望 ts_rank 把它排进前 60：短块词密度高，infobox 常被挤到 60 名外
    if pids:
        have = {c.pk for c, _ in scored}
        extra = (RagChunk.objects.select_related('page')
                 .filter(page_id__in=pids).order_by('chunk_index')[:80])
        scored += [(c, 0.0) for c in extra if c.pk not in have]
"""
assert old in s, '[FAIL] 锚点不匹配 — 把 retrieve() 开头 8 行发我'
s = s.replace(old, new, 1)

open(P, 'w', encoding='utf-8').write(s)
print('[OK] 已加实体整页进池')
print('[CHECK] 行数 :', len(s.splitlines()), '(期望 430 或 432)')
