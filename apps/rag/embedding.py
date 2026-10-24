"""apps/rag/embedding.py — Qwen(DashScope) 文本嵌入客户端

只在 D2（拿到 API Key 之后）使用：
    python manage.py rag_embed --init          # 建 vector 列 + HNSW 索引
    python manage.py rag_embed --probe         # 探测真实维度
    python manage.py rag_embed --all           # 全量向量化
    python manage.py rag_embed --page 780      # 单页重嵌

配置全部走 rag_setting 表：
    rag.embedding.api_key / rag.embedding.base_url / rag.embedding.model / rag.embedding.dim
"""
import hashlib
import json
import logging

import requests

from django.core.cache import cache

from .services import get_float, get_int, get_setting

logger = logging.getLogger(__name__)

_HTTP = requests.Session()   # 复用连接，省掉每次提问的 TCP+TLS

BATCH_DEFAULT = 10          # DashScope 单次 texts 上限保守值（首轮实测会确认）


class EmbeddingError(RuntimeError):
    pass


def _headers():
    key = (get_setting('rag.embedding.api_key') or '').strip()
    if not key:
        raise EmbeddingError('未配置 rag.embedding.api_key（用 manage.py rag_set --set 写入）')
    return {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}


def _endpoint():
    base = (get_setting('rag.embedding.base_url')
            or 'https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
    return base + '/embeddings'


def embed_batch(texts, dim=None, model=None):
    """返回 [[float, ...], ...]，顺序与 texts 一致"""
    if not texts:
        return []
    dim = int(dim or get_int('rag.embedding.dim', 1024))
    model = model or get_setting('rag.embedding.model') or 'text-embedding-v4'
    payload = {'model': model, 'input': texts, 'encoding_format': 'float'}
    if dim and dim > 0:
        payload['dimensions'] = dim
    resp = _HTTP.post(_endpoint(), headers=_headers(), json=payload, timeout=(10, 120))
    if resp.status_code >= 400:
        raise EmbeddingError(f'嵌入接口 {resp.status_code}: {resp.text[:300]}')
    data = resp.json()
    items = sorted(data.get('data', []), key=lambda x: x.get('index', 0))
    vecs = [it['embedding'] for it in items]
    if len(vecs) != len(texts):
        raise EmbeddingError(f'返回条数不匹配：请求 {len(texts)} 条，返回 {len(vecs)} 条')
    return vecs


def embed_query(text, dim=None):
    """查询向量带 Redis 缓存：同一个问题重复提问不再调 API（省约 270ms）"""
    dim = int(dim or get_int('rag.embedding.dim', 1024))
    ck = 'rag:qvec:%d:%s' % (dim, hashlib.md5((text or '').encode('utf-8')).hexdigest()[:16])
    hit = cache.get(ck)
    if hit:
        return hit
    vec = embed_batch([text], dim=dim)[0]
    try:
        cache.set(ck, vec, 3600)
    except Exception:                                          # noqa: BLE001
        pass
    return vec


def probe(text='防风草的售价是35金'):
    """实测维度 + 归一化长度，用于确定 vector(N) 的 N"""
    vecs = embed_batch([text], dim=0)          # dim=0 -> 不传 dimensions，拿模型默认维度
    v = vecs[0]
    norm = sum(x * x for x in v) ** 0.5
    return {
        'model': get_setting('rag.embedding.model'),
        'dim': len(v),
        'norm': round(norm, 6),
        'head': [round(x, 5) for x in v[:5]],
    }


def embed_texts(chunk_texts, batch=None, dim=None):
    """批量嵌入（带重试），产出 (index_offset, vectors)"""
    batch = batch or get_int('rag.embedding.batch', BATCH_DEFAULT)
    for i in range(0, len(chunk_texts), batch):
        part = chunk_texts[i:i + batch]
        for attempt in range(3):
            try:
                yield i, embed_batch(part, dim=dim)
                break
            except Exception as e:                             # noqa: BLE001
                if attempt == 2:
                    raise
                logger.warning('嵌入第 %d 批失败(%s)，重试', i, e)


def search_by_vector(question, limit=40):
    """D2：向量通道。返回 [(chunk, score)]，score 已归一化到 0~1"""
    from django.db import connection

    dim = get_int('rag.embedding.dim', 1024)
    vec = embed_query(question, dim=dim)
    literal = '[' + ','.join(f'{x:.6f}' for x in vec) + ']'
    sql = """
        SELECT id, 1 - (embedding <=> %s::vector) AS score
        FROM rag_chunk
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    with connection.cursor() as cur:
        cur.execute(sql, [literal, literal, limit])
        rows = cur.fetchall()
    if not rows:
        return []
    from .models import RagChunk
    ids = [r[0] for r in rows]
    score_map = {r[0]: float(r[1]) for r in rows}
    chunks = RagChunk.objects.select_related('page').filter(pk__in=ids)
    # 向量相似度 0~1 要压到与 BM25/实体命中可比的范围
    w = get_float('rag.vector_weight', 1.8)
    return [(c, score_map[c.pk] * w) for c in chunks]
