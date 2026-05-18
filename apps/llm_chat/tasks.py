from .models import LLMTask
from django.utils import timezone

def create_llm_task(uid, conversation, model_name):
    task = LLMTask.objects.create(
        uid_id=uid,
        conversation=conversation,
        model_name=model_name,
        status='pending'
    )
    return task

def update_task_status(task, status, error=None):
    task.status = status
    if status in ['completed', 'failed']:
        task.finished_at = timezone.now()
    if error:
        task.error_message = error
    task.save()