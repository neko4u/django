# -*- coding: utf-8 -*-
"""检索打分改为"字面覆盖率"，绕开 zhparser 分词不一致（天成/成熟）"""
P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()

if 'def _literal_coverage(' in s:
    print('[SKIP] 已经是字面覆盖率版本')
    raise SystemExit(0)

anchor = 'def _lexemes('
add = '''def _q_chars(question):
    """把问题里的标点/空白全部去掉，只留中英文数字"""
    return re.sub(r"[^\\u4e00-\\u9fff0-9a-zA-Z]+", '', question or '')


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


'''
assert anchor in s, '[FAIL] 找不到 _lexemes'
s = s.replace(anchor, add + anchor, 1)

old = """    if scored and terms:
        tvmap = _lexemes([c for c, _ in scored])
        rescored = []
        n = len(terms)
        for c, rank in scored:
            tv = tvmap.get(c.pk) or set()
            cover = sum(1 for t in terms if t in tv) / n
            head = 0.25 if any(t in (c.header_path or '') for t in terms) else 0.0
            rescored.append((c, cover + head + 0.3 * min(1.0, rank)))
        scored = rescored
"""
new = """    qc = _q_chars(question)
    if scored and qc:
        rescored = []
        for c, rank in scored:
            cover = _literal_coverage(qc, c.content or '')
            head = 0.25 if _literal_coverage(qc, c.header_path or '') > 0.34 else 0.0
            rescored.append((c, cover + head + 0.3 * min(1.0, rank)))
        scored = rescored
"""
assert old in s, '[FAIL] 打分段锚点不匹配'
s = s.replace(old, new, 1)

open(P, 'w', encoding='utf-8').write(s)
print('[OK] 改用字面覆盖率打分')
print('[CHECK] _q_chars          :', 'def _q_chars(' in s)
print('[CHECK] _literal_coverage :', 'def _literal_coverage(' in s)
print('[CHECK] 行数              :', len(s.splitlines()), '(期望 462 或 464)')
