P = '/opt/projects/project1/apps/rag/services.py'
s = open(P, encoding='utf-8').read()
backup = open(P, encoding='utf-8').read()
changed = []

if 'from django.conf import settings' not in s:
    old = 'from django.contrib.postgres.search import SearchQuery, SearchRank'
    assert old in s, '[FAIL] 找不到 import 锚点'
    s = s.replace(old, 'from django.conf import settings\n' + old, 1)
    changed.append('import')

if '_from_settings' not in s:
    old = """def get_setting(key, default=None):
    ck = 'rag:setting:' + key
    val = cache.get(ck)
    if val is None:
        try:
            val = RagSetting.objects.get(pk=key).value
        except RagSetting.DoesNotExist:
            val = DEFAULTS.get(key, default if default is not None else '')
        cache.set(ck, val, 60)
    return val"""
    new = '''def _from_settings(key):
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
        except Exception:                       # 表还没建等情况，不能让配置读取把请求打挂
            val = DEFAULTS.get(key, default if default is not None else '')
        cache.set(ck, val, 60)
    return val'''
    assert old in s, '[FAIL] 找不到 get_setting 锚点'
    s = s.replace(old, new, 1)
    changed.append('get_setting')

if changed:
    open(P + '.bak', 'w', encoding='utf-8').write(backup)
    open(P, 'w', encoding='utf-8').write(s)

print('[OK] 本次改动:', changed or '无（已经是新版）')
s = open(P, encoding='utf-8').read()
print('[CHECK] settings 导入 :', 'from django.conf import settings' in s)
print('[CHECK] _from_settings:', '_from_settings' in s)
print('[CHECK] 行数         :', len(s.splitlines()), '(目标是 361)')
