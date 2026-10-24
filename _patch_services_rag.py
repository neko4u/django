P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()
changed = False

# 1) 补 settings 导入
if 'from django.conf import settings' not in s:
    old = 'from django.contrib.postgres.search import SearchQuery, SearchRank'
    new = 'from django.conf import settings\n' + old
    assert old in s, '找不到导入锚点'
    s = s.replace(old, new, 1)
    changed = True
    print('[OK] 已加 from django.conf import settings')

# 2) get_setting 增加 settings 优先逻辑
if '_from_settings' in s:
    print('[SKIP] _from_settings 已存在')
else:
    old = """def get_setting(key, default=None):
    ck = 'rag:setting:' + key"""
    new = """def _from_settings(key):
    \"\"\"rag.embedding.* 优先从 settings.RAG_EMBEDDING 读（/opt/config/django/project1settings.json）\"\"\"
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
    ck = 'rag:setting:' + key"""
    assert old in s, '找不到 get_setting 锚点'
    s = s.replace(old, new, 1)
    changed = True
    print('[OK] 已加 _from_settings 优先逻辑')

if changed:
    open(P + '.bak', 'w', encoding='utf-8').write(open(P, encoding='utf-8').read())
    open(P, 'w', encoding='utf-8').write(s)

s = open(P, encoding='utf-8').read()
print('[CHECK] _from_settings:', '_from_settings' in s)
print('[CHECK] settings 导入:', 'from django.conf import settings' in s)
