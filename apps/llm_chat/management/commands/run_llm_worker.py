import time
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = '启动 LLM 任务 Worker（当前为占位模式）'

    def handle(self, *args, **options):
        self.stdout.write('LLM Worker started (placeholder mode). Press Ctrl+C to stop.')
        try:
            while True:
                # 未来将从 Redis 队列中取任务并执行
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped.')