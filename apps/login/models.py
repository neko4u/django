from django.db import models
from django.utils import timezone
from django.dispatch import receiver
from django.core.validators import FileExtensionValidator
import uuid

# Create your models here.
class UserInfo(models.Model):
    uid = models.AutoField(primary_key=True, verbose_name="UID")
    account = models.CharField(verbose_name="账户名称",max_length=32)
    password = models.CharField(verbose_name="密码",max_length=128)
    email = models.CharField(verbose_name="邮箱",max_length=32)
    name = models.CharField(verbose_name="昵称",max_length=16,default="momo") #nickname
    phone = models.CharField(verbose_name="手机号码", max_length=11)
    salt = models.CharField(verbose_name="salt",max_length=128)
    create_time = models.DateTimeField(default=timezone.now)
    update_time = models.DateTimeField(default=timezone.now)
    login_time = models.DateTimeField(default=timezone.now)
    is_delete = models.BooleanField(default=False)
    avatar = models.ImageField(
        upload_to='avatars/',
        default='avatars/default/default.png',
        null=True,
        blank=True,
        verbose_name="用户头像",
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'png', 'jpeg']),
        ],
        help_text="允许的格式：jpg/png，最大2MB"
    )

    # def save(self, *args, **kwargs):
    #     if self.uid:  # 更新现有记录时
    #         try:
    #             old = UserInfo.objects.get(uid=self.uid)
    #             if old.avatar and old.avatar != self.avatar:
    #                 old.avatar.delete(save=False)
    #         except UserInfo.DoesNotExist:
    #             pass
    #     super().save(*args, **kwargs)
    
    # def upload_to(instance, filename):
    #     return f'avatars/{instance.uid}.{filename.split(".")[-1]}'

class Post(models.Model):
    pid = models.AutoField(primary_key=True, verbose_name="postUid")
    powner = models.ForeignKey(
        UserInfo,
        on_delete=models.CASCADE,
        verbose_name="发布者"
    )
    title = models.CharField(verbose_name="标题", max_length=200)
    content = models.TextField(verbose_name="内容", max_length=1000)
    cover_image = models.ImageField(
        upload_to='post_covers/',
        null=True,
        blank=True,
        verbose_name="封面图",
        validators=[FileExtensionValidator(['jpg', 'png', 'jpeg'])],
    )
    comment_count = models.PositiveIntegerField(default=0, verbose_name="评论数")

    create_time = models.DateTimeField(default=timezone.now)
    latest_comment_time = models.DateTimeField(default=timezone.now)
    like_count = models.PositiveIntegerField(default=0, verbose_name="点赞数")
    view_count = models.PositiveIntegerField(default=0, verbose_name="浏览数")
    is_hidden = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)

class Comment(models.Model):
    COMMENT_TYPE_CHOICES = (
        ('post', '主评论'),
        ('comment', '回复评论'),
    )
    cid = models.AutoField(primary_key=True, verbose_name="评论ID")
    content = models.TextField(verbose_name="评论内容", max_length=250)
    cowner = models.ForeignKey(
        UserInfo, 
        on_delete=models.CASCADE,
        verbose_name="评论者",
        related_name="comments"
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        verbose_name="关联帖子",
        related_name="post_comments"
    )
    create_time = models.DateTimeField(default=timezone.now)
    is_delete = models.BooleanField(default=False)
    parent_comment = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="父级评论",
        related_name="replies",
        default=0,
    )
    root_comment = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name="根评论",
        related_name="descendants",
        default=0,
    )
    comment_type = models.CharField(
        max_length=10,
        choices=COMMENT_TYPE_CHOICES,
        default='post',
        verbose_name="评论类型"
    )
    
    like_count = models.PositiveIntegerField(default=0, verbose_name="点赞数")
    
    def save(self, *args, **kwargs):
        if self.parent_comment:
            self.root_comment = self.parent_comment.root_comment or self.parent_comment
            self.comment_type = 'comment'
        super().save(*args, **kwargs)
        if not self.is_delete:
            self.post.comment_count = Comment.objects.filter(
                post=self.post, 
                is_delete=False,
                comment_type='post'
            ).count()
            self.post.save()

class Post_Like(models.Model):
    user = models.ForeignKey(
        UserInfo,
        verbose_name="用户",
        on_delete=models.CASCADE,
        )
    post = models.ForeignKey(
        Post,
        verbose_name="帖子",
        on_delete=models.CASCADE,
        )
    created_at = models.DateTimeField(default=timezone.now)

class Comment_Like(models.Model):
    user = models.ForeignKey(
        UserInfo,
        verbose_name="用户",
        on_delete=models.CASCADE,
        )
    comment = models.ForeignKey(
        Comment,
        verbose_name="评论",
        on_delete=models.CASCADE,
        )
    post = models.ForeignKey(
        Post,
        verbose_name="帖子",
        on_delete=models.CASCADE,
        )
    created_at = models.DateTimeField(default=timezone.now)

# FRP页面权限
class FrpPermission(models.Model):
    """
    FRP 权限表
    """
    user = models.OneToOneField(UserInfo, on_delete=models.CASCADE, related_name='frp_perm', verbose_name="关联用户")
    can_access = models.BooleanField(default=False, verbose_name="允许访问页面")
    can_start = models.BooleanField(default=False, verbose_name="允许启动")
    can_stop = models.BooleanField(default=False, verbose_name="允许停止")
    can_restart = models.BooleanField(default=False, verbose_name="允许重启")
    can_get_new_token = models.BooleanField(default=False, verbose_name="允许刷新Token")
    
    class Meta:
        db_table = 'frp_permission'
        verbose_name = 'FRP权限配置'

class CommentGenerationTask(models.Model):
    STATUS_CHOICES = (
        ('pending', '等待中'),
        ('running', '执行中'),
        ('success', '成功'),
        ('failed', '失败'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(UserInfo, on_delete=models.CASCADE, related_name='submitted_tasks') 
    author = models.ForeignKey(UserInfo, on_delete=models.CASCADE, related_name='generated_comments_tasks')
    pid = models.IntegerField(verbose_name='帖子ID')
    num = models.IntegerField(default=1, verbose_name='生成条数')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    result = models.TextField(blank=True, verbose_name='结果信息')  # 存放错误信息或成功摘要

    class Meta:
        ordering = ['-created_at']