import datetime
import json
import os
import sys

P = '/opt/config/django/project1settings.json'
key = os.environ.get('QK', '').strip()

if not key:
    sys.exit('[FAIL] 没有收到 key（环境变量 QK 为空）')
if not key.startswith('sk-'):
    sys.exit(f'[FAIL] key 格式不对，应以 sk- 开头，实际开头是 {key[:4]!r}')

d = json.load(open(P, encoding='utf-8'))
sec = d.setdefault('rag_embedding', {})
sec['api_key'] = key
sec.setdefault('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
sec.setdefault('model', 'text-embedding-v4')
sec.setdefault('dim', 1024)
sec.setdefault('batch', 10)

bak = P + '.bak.' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
tmp = P + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
json.load(open(tmp, encoding='utf-8'))          # 写出去再读回来校验一遍
os.chmod(tmp, 0o600)
os.replace(tmp, P)                              # 原子替换

print('[OK] 已写入', P)
print('[OK] 备份  ', bak)
print('[OK] rag_embedding =', {k: (v if k != 'api_key' else v[:6] + '...' + v[-4:]) for k, v in sec.items()})
