import time
import traceback
from django.core.management.base import BaseCommand
from django.core.cache import cache
from apps.login.models import CommentGenerationTask, Comment
from apps.login.services import ForumService

class Command(BaseCommand):
    help = '启动 Redis 任务队列工作者'

    def handle(self, *args, **options):
        redis_client = cache.client.get_client()
        self.stdout.write('Worker started, waiting for tasks...')
        while True:
            task_id_bytes = redis_client.brpop('task:comment_queue', timeout=0)
            if task_id_bytes:
                task_id = task_id_bytes[1].decode()
                try:
                    self.process_task(task_id)
                except Exception as e:
                    self.stderr.write(f'处理任务 {task_id} 时发生未捕获异常: {e}')
                    self.stderr.write(traceback.format_exc())

    def process_task(self, task_id):
        self.stdout.write(f"开始处理任务 {task_id}")
        try:
            task = CommentGenerationTask.objects.select_related('author', 'operator').get(id=task_id)
        except CommentGenerationTask.DoesNotExist:
            self.stderr.write(f'Task {task_id} not found')
            return
        except Exception as e:
            self.stderr.write(f'获取任务 {task_id} 时出错: {e}')
            return

        task.status = 'running'
        task.save(update_fields=['status'])
        self.stdout.write(f"任务作者: {task.author.uid}, 帖子ID: {task.pid}, 条数: {task.num}")

        success_count = 0
        task.result = ''
        for i in range(task.num):
            self.stdout.write(f"开始生成第 {i+1} 条评论")
            try:
                result = ForumService.ad_create_comment(
                    user=task.author,
                    post_id=task.pid,
                    comment_type=1,
                    par_cid=None,
                    root_cid=None,
                )
                if not isinstance(result, Comment):
                    raise Exception(f"生成失败，返回值异常: {result}")
                self.stdout.write(f"第 {i+1} 条生成成功")
                success_count += 1

            except Exception as e:
                error_msg = f'生成评论失败 (第{i+1}条): {e}'
                self.stderr.write(error_msg)
                task.result += error_msg + "\n"

        if success_count == task.num:
            task.status = 'success'
            task.result = f'成功生成 {task.num} 条评论'
        else:
            task.status = 'failed'
            task.result = f'部分成功: {success_count}/{task.num} 条\n' + (task.result if task.result else '')
        task.save(update_fields=['status', 'result'])
        self.stdout.write(f"任务 {task_id} 处理完成，状态: {task.status}")