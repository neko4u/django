# -*- coding: utf-8 -*-
"""L1 别名词典：问题里的社区口语 → 追加页面标题参与检索（不改原词，只追加）"""
import io
P = '/opt/projects/project1/apps/rag/services.py'
s = io.open(P, encoding='utf-8').read()

if 'def _alias_map(' in s:
    print('[SKIP] 别名逻辑已存在')
    raise SystemExit(0)

anchor = 'def _all_pages('
assert anchor in s, '[FAIL] 找不到 _all_pages'
add = '''def _alias_map():
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


'''
s = s.replace(anchor, add + anchor, 1)

old = """    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)"""
new = """    question, alias_hits = _expand_aliases(question)
    if alias_hits:
        logger.info('别名命中: %s', alias_hits)
    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)"""
assert old in s, '[FAIL] retrieve 锚点不匹配（未写入）'
s = s.replace(old, new, 1)

io.open(P, 'w', encoding='utf-8').write(s)
print('[OK] 已加别名词典')
print('[CHECK] _alias_map     :', 'def _alias_map(' in s)
print('[CHECK] _expand_aliases:', 'def _expand_aliases(' in s)
print('[CHECK] 行数           :', len(s.splitlines()), '(期望 486 或 484)')
