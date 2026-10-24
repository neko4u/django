"""manage.py rag_setup —— 确保 pgvector / zhparser 扩展与中文检索配置存在

    python manage.py rag_setup
    python manage.py rag_setup --config simple     # 放弃中文分词，退回默认

需要 superuser 的操作（CREATE EXTENSION）如果失败，会打印手工命令，不中断。
"""
from django.core.management.base import BaseCommand
from django.db import connection

MAPPING = 'n,v,a,i,e,l,j,t,q,b,s,z,m'


class Command(BaseCommand):
    help = '准备 RAG 依赖的 PostgreSQL 扩展与中文文本检索配置'

    def add_arguments(self, parser):
        parser.add_argument('--config', default='zh', help='要创建的文本检索配置名，默认 zh')

    def handle(self, *args, **opts):
        cfg = opts['config']

        with connection.cursor() as cur:
            cur.execute('SHOW server_version')
            self.stdout.write(f'[*] PostgreSQL {cur.fetchone()[0]}')

            # 1) 扩展
            for ext in ('vector', 'zhparser'):
                try:
                    cur.execute(f'CREATE EXTENSION IF NOT EXISTS {ext}')
                    cur.execute('SELECT 1 FROM pg_extension WHERE extname=%s', [ext])
                    self.stdout.write(self.style.SUCCESS(f'[OK] extension {ext}'))
                except Exception as e:                          # noqa: BLE001
                    connection.rollback()
                    self.stdout.write(self.style.WARNING(
                        f'[WARN] extension {ext} 创建失败：{e}\n'
                        f'       请用 superuser 执行一次：\n'
                        f'       sudo -u postgres psql -d {connection.settings_dict["NAME"]} '
                        f'-c "CREATE EXTENSION IF NOT EXISTS {ext}"'
                    ))

            if cfg == 'simple':
                self.stdout.write('[SKIP] 使用 simple 配置，不建中文分词')
                return

            # 2) 文本检索配置
            cur.execute('SELECT 1 FROM pg_ts_config WHERE cfgname=%s', [cfg])
            if cur.fetchone():
                self.stdout.write(self.style.SUCCESS(f'[OK] 文本检索配置 {cfg} 已存在'))
            else:
                try:
                    cur.execute(f'CREATE TEXT SEARCH CONFIGURATION {cfg} (PARSER = zhparser)')
                    cur.execute(
                        f'ALTER TEXT SEARCH CONFIGURATION {cfg} '
                        f'ADD MAPPING FOR {MAPPING} WITH simple'
                    )
                    self.stdout.write(self.style.SUCCESS(f'[OK] 已创建文本检索配置 {cfg}'))
                except Exception as e:                      # noqa: BLE001
                    connection.rollback()
                    self.stdout.write(self.style.ERROR(
                        f'[FAIL] 创建配置 {cfg} 失败：{e}\n'
                        f'       大概率是 zhparser 扩展没装上，先解决上一步再重跑。'
                    ))
                    return

            # 3) 自检
            try:
                cur.execute("SELECT to_tsvector(%s::regconfig, %s)::text", [cfg, '防风草的售价是35金，春季种4天成熟'])
                tv = cur.fetchone()[0]
                self.stdout.write(f'[TEST] to_tsvector = {tv}')
                cur.execute("SELECT to_tsvector(%s::regconfig,%s) @@ plainto_tsquery(%s::regconfig,%s)",
                            [cfg, '防风草的售价是35金', cfg, '防风草'])
                self.stdout.write(f'[TEST] 命中测试 = {cur.fetchone()[0]}')
                self.stdout.write(self.style.SUCCESS(
                    f'[DONE] 配置就绪。下一步：manage.py rag_load --file chunks.ndjson'
                ))
            except Exception as e:                          # noqa: BLE001
                connection.rollback()
                self.stdout.write(self.style.WARNING(f'[WARN] 自检失败：{e}'))
