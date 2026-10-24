"""manage.py rag_load —— 把 build_chunks.py 产出的 chunks.ndjson 灌进库

    python manage.py rag_load --file /opt/projects/project1/data/chunks.ndjson --reset
    python manage.py rag_load --file chunks.ndjson --limit 20      # 先试 20 页
    python manage.py rag_load --rebuild-fts                        # 只重建检索向量

灌完会自动生成 tsvector（zhparser），不需要额外步骤。
"""
import json
from collections import OrderedDict

from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.rag.models import RagChunk, RagPage


class Command(BaseCommand):
    help = '导入 chunk 数据并建立全文检索向量'

    def add_arguments(self, parser):
        parser.add_argument('--file', default=None, help='chunks.ndjson 路径')
        parser.add_argument('--reset', action='store_true', help='先清空 rag_chunk / rag_page')
        parser.add_argument('--limit', type=int, default=0, help='只导入前 N 个页面（调试用）')
        parser.add_argument('--config', default='zh', help='全文检索配置，默认 zh')
        parser.add_argument('--batch', type=int, default=2000, help='tsvector 每批行数')
        parser.add_argument('--rebuild-fts', action='store_true', help='只重建已有数据的 tsvector')

    def handle(self, *args, **opts):
        if not opts['rebuild_fts']:
            if not opts['file']:
                raise CommandError('缺少 --file（或改用 --rebuild-fts）')
            self._load(opts['file'], opts)
        self._build_fts(opts['config'], opts['batch'])

    # ------------------------------------------------------------------ 导入
    def _load(self, path, opts):
        pages = OrderedDict()
        bad = 0
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                pid = c.get('page_id')
                if not pid:
                    bad += 1
                    continue
                p = pages.setdefault(pid, {
                    'title': c.get('title', ''),
                    'revid': c.get('revid', 0),
                    'wiki_url': c.get('wiki_url', ''),
                    'updated_raw': c.get('updated_raw', ''),
                    'chunks': [],
                })
                p['chunks'].append(c)

        if opts['limit']:
            pages = OrderedDict(list(pages.items())[:opts['limit']])
        if not pages:
            raise CommandError('文件里没有可导入的数据')

        total_chunks = sum(len(p['chunks']) for p in pages.values())
        self.stdout.write(f'[*] 待导入 {len(pages)} 页 / {total_chunks} 条切片（坏行 {bad}）')

        with transaction.atomic():
            created_pages = 0
            for pid, p in pages.items():
                RagPage.objects.update_or_create(
                    page_id=pid,
                    defaults={
                        'title': p['title'][:255],
                        'revid': p['revid'] or 0,
                        'wiki_url': p['wiki_url'][:500],
                        'updated_raw': p['updated_raw'][:200],
                        'chunk_count': len(p['chunks']),
                    },
                )
                created_pages += 1
                RagChunk.objects.filter(page_id=pid).delete()

                RagChunk.objects.bulk_create([
                    RagChunk(
                        page_id=pid,
                        chunk_index=int(c.get('chunk_index') or 0),
                        content=c.get('content', ''),
                        content_type=(c.get('content_type') or 'paragraph')[:20],
                        header_path=(c.get('header_path') or '')[:300],
                        images=c.get('images') or [],
                        char_count=int(c.get('char_count') or len(c.get('content', ''))),
                        token_count=int(c.get('token_count') or 0),
                        content_hash=(c.get('content_hash') or '')[:64],
                        revid=int(c.get('revid') or 0),
                    )
                    for c in p['chunks']
                ], batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f'[OK] 导入完成：{created_pages} 页 / {total_chunks} 条切片'
        ))

    # ------------------------------------------------------------------ tsvector
    def _build_fts(self, cfg, batch):
        total = RagChunk.objects.count()
        if not total:
            self.stdout.write('[SKIP] 没有切片可建索引')
            return

        for config in ([cfg, 'simple'] if cfg != 'simple' else ['simple']):
            try:
                with connection.cursor() as cur:                 # 先确认配置真的可用
                    cur.execute('SELECT 1 FROM pg_ts_config WHERE cfgname=%s', [config])
                    if not cur.fetchone():
                        raise RuntimeError(f'文本检索配置 {config} 不存在')
                    cur.execute('SELECT to_tsvector(%s::regconfig, %s)', [config, '测试 test'])

                done = 0
                ids = list(RagChunk.objects.values_list('pk', flat=True))
                for i in range(0, len(ids), batch):
                    part = ids[i:i + batch]
                    RagChunk.objects.filter(pk__in=part).update(
                        search_vector=SearchVector('content', config=config)
                    )
                    done += len(part)
                    self.stdout.write(f'    tsvector {done}/{len(ids)}', ending='\r')
                    self.stdout.flush()
                self.stdout.write('')
                with connection.cursor() as cur:
                    cur.execute('SELECT count(*) FROM rag_chunk WHERE search_vector IS NOT NULL')
                    n = cur.fetchone()[0]
                self.stdout.write(self.style.SUCCESS(
                    f'[OK] tsvector(config={config}) 完成：{n}/{total} 条'
                ))
                if config != cfg:
                    self.stdout.write(self.style.WARNING(
                        f'[WARN] 没有 {cfg} 配置，已退回 simple（中文按单字切，召回较差）'
                        f' —— 先跑 manage.py rag_setup'
                    ))
                return
            except Exception as e:                               # noqa: BLE001
                connection.rollback()
                self.stdout.write(self.style.WARNING(f'[WARN] config={config} 建索引失败：{e}'))
        raise CommandError('tsvector 建不起来，检查 rag_setup 的输出')
