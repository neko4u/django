P = '/opt/projects/project1/project1/settings.py'
s = open(P, encoding='utf-8').read()

if 'RAG_EMBEDDING' in s:
    print('[SKIP] RAG_EMBEDDING 已存在')
else:
    old = "OPENAI_KIMI_BASE_URL = config.get('openai_kimi', {}).get('base_url', '')"
    new = old + "\nRAG_EMBEDDING = config.get('rag_embedding', {}) or {}"
    if old not in s:
        print('[FAIL] 找不到锚点')
    else:
        open(P + '.bak', 'w', encoding='utf-8').write(s)
        open(P, 'w', encoding='utf-8').write(s.replace(old, new, 1))
        print('[OK] settings.py 已加 RAG_EMBEDDING')

s = open(P, encoding='utf-8').read()
for line in s.splitlines():
    if 'RAG_EMBEDDING' in line:
        print('  >', line.strip())
