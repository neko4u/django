# -*- coding: utf-8 -*-
"""向量分权重可调：rag.vector_weight 默认 1.8（原 1.2 被字面覆盖率压死）"""
import re

# 1) services.py 的 DEFAULTS 里加配置项
P1 = '/opt/projects/project1/apps/rag/services.py'
s1 = open(P1, encoding='utf-8').read()
if 'rag.vector_weight' not in s1:
    old = "    'rag.rag.embedding"  # 占位，下面用真实锚点
    anchor = "    'rag.embedding.api_key': '',\n}"
    new = "    'rag.embedding.api_key': '',\n    'rag.vector_weight': '1.8',\n}"
    assert anchor in s1, '[FAIL] services.py DEFAULTS 锚点不匹配'
    s1 = s1.replace(anchor, new, 1)
    open(P1, 'w', encoding='utf-8').write(s1)
    print('[OK] services.py 加了 rag.vector_weight')
else:
    print('[SKIP] rag.vector_weight 已存在')

# 2) embedding.py 里用这个权重
P2 = '/opt/projects/project1/apps/rag/embedding.py'
s2 = open(P2, encoding='utf-8').read()
if 'rag.vector_weight' in s2:
    print('[SKIP] embedding.py 已经用权重')
else:
    if 'from .services import get_int, get_setting' in s2:
        s2 = s2.replace('from .services import get_int, get_setting',
                        'from .services import get_float, get_int, get_setting', 1)
    else:
        raise AssertionError('[FAIL] embedding.py 导入行不匹配')

    old = "    return [(c, score_map[c.pk] * 1.2) for c in chunks]"
    new = "    w = get_float('rag.vector_weight', 1.8)\n    return [(c, score_map[c.pk] * w) for c in chunks]"
    assert old in s2, '[FAIL] embedding.py 返回值锚点不匹配'
    s2 = s2.replace(old, new, 1)
    open(P2, 'w', encoding='utf-8').write(s2)
    print('[OK] embedding.py 改用 rag.vector_weight')

print('[CHECK] services 行数 :', len(open(P1, encoding='utf-8').read().splitlines()))
print('[CHECK] embedding 行数:', len(open(P2, encoding='utf-8').read().splitlines()))
