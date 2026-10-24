"""manage.py rag_embed —— D2：向量化（拿到 Qwen Key 之后再跑）

    python manage.py rag_embed --probe        # 1. 探测真实维度（确认 dim）
    python manage.py rag_set --set rag.embedding.dim=1024
    python manage.py rag_embed --init         # 2. 加 embedding 列
    python manage.py rag_embed --all          # 3. 全量向量化
    python manage.py rag_embed --reindex      # 4. 建 HNSW 索引（灌完再建，快得多）

    python manage.py rag_embed --page 780     # 单页重嵌
    python manage.py rag_embed --all --force  # 忽略已有向量，全部重来
"""
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.rag.embedding import embed_batch, probe
from apps.rag.models import RagChunk
from apps.rag.services import get_int, get_setting


class Command(BaseCommand):
    help = 'RAG 向量化（Qwen text-embedding-v4）'

    def add_arguments(self, parser):
        parser.add_argument('--init', action='store_true', help='添加 embedding 列')
        parser.add_argument('--probe', action='store_true', help='探测模型真实维度')
        parser.add_argument('--all', action='store_true', help='全量向量化')
        parser.add_argument('--page', type=int, default=0, help='只重嵌指定 page_id')
        parser.add_argument('--reindex', action='store_true', help='建 HNSW 索引')
        parser.add_argument('--force', action='store_true', help='忽略已有向量')
        parser.add_argument('--batch', type=int, default=0, help='每批条数')
        parser.add_argument('--limit', type=int, default=0, help='最多处理 N 条')

    def handle(self, *args, **opts):
        if opts['probe']:
            return self._probe()
        if opts['init']:
            return self._init()
        if opts['reindex']:
            return self._reindex()
        if opts['all'] or opts['page']:
            return self._embed(opts)
        self.stdout.write(self.style.WARNING('没有指定动作，可用：--probe / --init / --all / --page N / --reindex'))

    # ------------------------------------------------------------------
    def _probe(self):
        self.stdout.write(f'[*] model = {get_setting("rag.embedding.model")}')
        self.stdout.write(f'[*] base  = {get_setting("rag.embedding.base_url")}')
        try:
            info = probe()
        except Exception as e:                                # noqa: BLE001
            raise CommandError(f'探测失败：{e}')
        self.stdout.write(self.style.SUCCESS(f'[OK] 真实维度 = {info["dim"]}，向量模长 = {info["norm"]}'))
        self.stdout.write(f'     前 5 维 = {info["head"]}')
        if info['dim'] != get_int('rag.embedding.dim', 0):
            self.stdout.write(self.style.WARNING(
                f'[!] 与配置的 rag.embedding.dim={get_int("rag.embedding.dim", 0)} 不一致，'
                f'先执行：manage.py rag_set --set rag.embedding.dim={info["dim"]}'
            ))

    def _init(self):
        dim = get_int('rag.embedding.dim', 1024)
        if dim <= 0:
            raise CommandError('rag.embedding.dim 未设置')
        with connection.cursor() as cur:
            cur.execute('CREATE EXTENSION IF NOT EXISTS vector')
            cur.execute('SELECT 1 FROM information_schema.columns '
                        'WHERE table_name=%s AND column_name=%s', ['rag_chunk', 'embedding'])
            if cur.fetchone():
                cur.execute("SELECT atttypmod FROM pg_attribute "
                            "WHERE attrelid='rag_chunk'::regclass AND attname='embedding'")
                self.stdout.write(self.style.WARNING(
                    f'[!] embedding 列已存在（typmod={cur.fetchone()[0]}），跳过。'
                    f'如需改维度必须先 DROP COLUMN 再重跑 --init 并全量重嵌。'
                ))
                return
            cur.execute(f'ALTER TABLE rag_chunk ADD COLUMN embedding vector({dim})')
        self.stdout.write(self.style.SUCCESS(f'[OK] 已添加 embedding vector({dim})'))

    def _reindex(self):
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM rag_chunk WHERE embedding IS NOT NULL')
            n = cur.fetchone()[0]
            if not n:
                raise CommandError('还没有任何向量，先跑 --all')
            self.stdout.write(f'[*] 已向量化 {n} 条，开始建 HNSW（m=16, ef_construction=64）...')
            t0 = time.time()
            cur.execute('DROP INDEX IF EXISTS rag_chunk_emb_hnsw')
            cur.execute(
                'CREATE INDEX rag_chunk_emb_hnsw ON rag_chunk '
                'USING hnsw (embedding vector_cosine_ops) '
                'WITH (m=16, ef_construction=64)'
            )
            cur.execute('ANALYZE rag_chunk')
        self.stdout.write(self.style.SUCCESS(f'[OK] 索引建好，耗时 {time.time() - t0:.1f}s'))

    # ------------------------------------------------------------------
    def _embed(self, opts):
        dim = get_int('rag.embedding.dim', 1024)
        batch = opts['batch'] or get_int('rag.embedding.batch', 10)
        model = get_setting('rag.embedding.model')

        qs = RagChunk.objects.all().order_by('pk')
        if opts['page']:
            qs = qs.filter(page_id=opts['page'])
        if not opts['force']:
            qs = qs.filter(embedding_dim=0)
        if opts['limit']:
            qs = qs[:opts['limit']]

        ids = list(qs.values_list('pk', flat=True))
        if not ids:
            self.stdout.write('[SKIP] 没有需要向量化的切片')
            return
        self.stdout.write(f'[*] 待向量化 {len(ids)} 条（model={model} dim={dim} batch={batch}）')

        t0 = time.time()
        done = 0
        for i in range(0, len(ids), batch):
            part = ids[i:i + batch]
            texts = list(RagChunk.objects.filter(pk__in=part).values_list('content', flat=True))
            for attempt in range(3):
                try:
                    vecs = embed_batch(texts, dim=dim)
                    break
                except Exception as e:                        # noqa: BLE001
                    if attempt == 2:
                        raise CommandError(f'第 {i} 批嵌入失败：{e}')
                    self.stdout.write(self.style.WARNING(f'    重试 {i}({attempt + 1}/3): {e}'))
                    time.sleep(2 * (attempt + 1))

            with connection.cursor() as cur:
                for cid, vec in zip(part, vecs):
                    lit = '[' + ','.join(f'{x:.6f}' for x in vec) + ']'
                    cur.execute(
                        'UPDATE rag_chunk SET embedding=%s::vector, embedding_model=%s, embedding_dim=%s '
                        'WHERE id=%s', [lit, model, len(vec), cid]
                    )
            done += len(part)
            speed = done / max(time.time() - t0, 0.001)
            self.stdout.write(f'    {done}/{len(ids)}  ({speed:.1f} 条/秒)', ending='\r')
            self.stdout.flush()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'[OK] 向量化完成 {done} 条，耗时 {time.time() - t0:.1f}s'
        ))
        self.stdout.write('    接着跑：manage.py rag_embed --reindex')
        self.stdout.write('    然后：  manage.py rag_set --set rag.retrieval_mode=hybrid')
