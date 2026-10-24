"""manage.py rag_set —— 读写 RAG 运行时配置（rag_setting 表）

    python manage.py rag_set --list
    python manage.py rag_set --get rag.llm_model
    python manage.py rag_set --set rag.llm_model=deepseek-chat rag.retrieval_mode=hybrid
    python manage.py rag_set --set rag.embedding.api_key=sk-xxxxxxxx
    python manage.py rag_set --del rag.llm_model
"""
from django.core.management.base import BaseCommand

from apps.rag.models import RagSetting
from apps.rag.services import DEFAULTS, clear_setting_cache


class Command(BaseCommand):
    help = '读写 RAG 配置'

    def add_arguments(self, parser):
        parser.add_argument('--set', nargs='*', default=None, help='key=value ...')
        parser.add_argument('--get', default=None)
        parser.add_argument('--del', dest='delete', default=None)
        parser.add_argument('--list', action='store_true')

    def handle(self, *args, **opts):
        changed = False
        for pair in (opts['set'] or []):
            if '=' not in pair:
                self.stderr.write(f'[SKIP] 不是 key=value：{pair}')
                continue
            k, v = pair.split('=', 1)
            RagSetting.objects.update_or_create(key=k.strip(), defaults={'value': v})
            self.stdout.write(self.style.SUCCESS(f'[SET] {k.strip()} = {v}'))
            changed = True

        if opts['delete']:
            n, _ = RagSetting.objects.filter(pk=opts['delete']).delete()
            self.stdout.write(self.style.SUCCESS(f'[DEL] {opts["delete"]} ({n})'))
            changed = True

        if changed:
            clear_setting_cache()

        if opts['get']:
            val = RagSetting.objects.filter(pk=opts['get']).values_list('value', flat=True).first()
            if val is None:
                self.stdout.write(f'[MISS] {opts["get"]} 未设置，默认值 = {DEFAULTS.get(opts["get"], "")!r}')
            else:
                masked = val if 'api_key' not in opts['get'] else (val[:6] + '...' + val[-4:] if len(val) > 12 else '***')
                self.stdout.write(f'{opts["get"]} = {masked}')

        if opts['list'] or not (opts['set'] or opts['get'] or opts['delete']):
            db = {r.key: r.value for r in RagSetting.objects.all()}
            self.stdout.write('\n--- 数据库里的配置 ---')
            if not db:
                self.stdout.write('  (空，全部走代码默认值)')
            for k, v in sorted(db.items()):
                vv = v if 'api_key' not in k else (v[:6] + '...' if v else '')
                self.stdout.write(f'  {k} = {vv}')
            self.stdout.write('\n--- 代码默认值（未覆盖时生效）---')
            for k, v in sorted(DEFAULTS.items()):
                if k not in db:
                    self.stdout.write(f'  {k} = {v}')
