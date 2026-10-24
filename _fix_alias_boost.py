# -*- coding: utf-8 -*-
"""别名目标页加权：让"夏季鱼王"压过"夏季"这种字面巧合（幂等，兼容已打/未打别名函数两种状态）"""
import io
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else '/opt/projects/project1'
P = BASE + '/apps/rag/services.py'
s = io.open(P, encoding='utf-8').read()
changed = []

# ---------- A. 别名函数（已打过的会跳过） ----------
if 'def _alias_map(' not in s:
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
    changed.append('A. 别名函数')

# ---------- B. 权重常量 ----------
if 'ALIAS_BOOST' not in s:
    anchor = '_HTTP = requests.Session()'
    assert anchor in s, '[FAIL] 找不到 _HTTP = requests.Session()'
    s = s.replace(anchor, anchor + '\n\n# 别名目标页的额外加权：别名是用户明确说出的映射，要压过字面巧合\nALIAS_BOOST = 0.6', 1)
    changed.append('B. ALIAS_BOOST 常量')

# ---------- C. retrieve 里算出 alias_pids ----------
old_c = """    question, alias_hits = _expand_aliases(question)
    if alias_hits:
        logger.info('别名命中: %s', alias_hits)
    pids = set(_entity_titles(question))"""
new_c = """    question, alias_hits = _expand_aliases(question)
    alias_pids = set()
    if alias_hits:
        alias_pids = set(RagPage.objects.filter(
            title__in=[t for _, t in alias_hits]).values_list('id', flat=True))
        logger.info('别名命中: %s → 页面 %s', alias_hits, alias_pids)
    pids = set(_entity_titles(question))"""
old_c0 = """    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)"""
new_c0 = """    question, alias_hits = _expand_aliases(question)
    alias_pids = set()
    if alias_hits:
        alias_pids = set(RagPage.objects.filter(
            title__in=[t for _, t in alias_hits]).values_list('id', flat=True))
        logger.info('别名命中: %s → 页面 %s', alias_hits, alias_pids)
    pids = set(_entity_titles(question))
    terms = _query_terms(question, cfg)"""
if 'alias_pids = set()' not in s:
    if old_c in s:
        s = s.replace(old_c, new_c, 1)
    elif old_c0 in s:
        s = s.replace(old_c0, new_c0, 1)
    else:
        raise SystemExit('[FAIL] C 段锚点不匹配（retrieve 开头）')
    changed.append('C. alias_pids')

# ---------- D. 候选池并入别名页 ----------
old_d = """    if pids:
        have = {c.pk for c, _ in scored}
        extra = (RagChunk.objects.select_related('page')
                 .filter(page_id__in=pids).order_by('chunk_index')[:80])"""
new_d = """    pool_pids = pids | alias_pids
    if pool_pids:
        have = {c.pk for c, _ in scored}
        extra = (RagChunk.objects.select_related('page')
                 .filter(page_id__in=pool_pids).order_by('chunk_index')[:80])"""
if 'pool_pids' not in s:
    assert old_d in s, '[FAIL] D 段锚点不匹配（候选池）'
    s = s.replace(old_d, new_d, 1)
    changed.append('D. 候选池')

# ---------- E. 兜底也带上别名页 ----------
old_e = "    scored += _entity_fallback(question, pids - hit_pages)"
if old_e in s:
    s = s.replace(old_e, "    scored += _entity_fallback(question, pool_pids - hit_pages)", 1)
    changed.append('E. 实体兜底')

# ---------- F. 合并前统一加权 ----------
old_f = "    merged = _merge(scored)"
new_f = """    # 别名目标页额外加权：必须放在向量合并之后，否则向量捞上来的块不带这个分
    if alias_pids:
        scored = [(c, s + (ALIAS_BOOST if c.page_id in alias_pids else 0.0)) for c, s in scored]

    merged = _merge(scored)"""
if '别名目标页额外加权' not in s:
    assert s.count(old_f) == 1, '[FAIL] F 段锚点不唯一（出现 %d 次）' % s.count(old_f)
    s = s.replace(old_f, new_f, 1)
    changed.append('F. 别名加权')

io.open(P, 'w', encoding='utf-8').write(s)
print('[OK] 改动 %d 处：' % len(changed))
for c in changed:
    print('   -', c)
print()
print('[CHECK] ALIAS_BOOST   :', [l for l in s.splitlines() if l.startswith('ALIAS_BOOST')])
print('[CHECK] alias_pids    :', 'alias_pids = set()' in s)
print('[CHECK] pool_pids     :', 'pool_pids = pids | alias_pids' in s)
print('[CHECK] 行数          :', len(s.splitlines()))
