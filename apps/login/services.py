# login/services.py

from django.utils import timezone
import time
from django.conf import settings
from django.db.models import Q, F
from .models import UserInfo, Post, Comment, Post_Like, Comment_Like
import bcrypt
import os
import re
import traceback
import logging
from django.db import transaction
from django.db.models import Prefetch
from openai import OpenAI
from django.conf import settings
import jwt
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class AuthenticationService:
    @staticmethod
    def authenticate_user(username, password):
        user = UserInfo.objects.filter(account=username).first()
        if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return user
        return None

    @staticmethod
    def login_session_data(user):
        login_time = timezone.now()
        user.login_time = login_time
        user.save(update_fields=['login_time'])

        return {
            "account": user.account,
            "userName": user.name,
            "uid": user.uid,
            "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            "login_time": login_time.strftime("%Y-%m-%d %H:%M:%S"),
            "avatar": user.avatar.url if user.avatar else None,
        }
    
    @staticmethod
    def register_user(form):
        """根据验证通过的表单创建新用户"""
        user = form.save(commit=False)
        pwd = form.cleaned_data['pwd'].encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_pwd = bcrypt.hashpw(pwd, salt).decode('utf-8')
        user.password = hashed_pwd
        user.salt = salt.decode('utf-8')
        # avatar字段已由ModelForm处理
        user.save()
        return user


class AvatarService:
    @staticmethod
    def handle_avatar_upload(user, file):
        AVATAR_DIR = os.path.join(settings.MEDIA_ROOT, 'avatars')
        os.makedirs(AVATAR_DIR, exist_ok=True)
        
        valid_extensions = ['.jpg', '.jpeg', '.png']

        filename = file.name
        _, ext = os.path.splitext(filename)
        ext = ext.lower() if ext else '.jpg'
        if ext not in valid_extensions:
            raise ValueError(f"不支持的文件类型: {ext}")

        filename = f"{user.uid}{ext}"
        save_path = os.path.join(AVATAR_DIR, filename)

        if os.path.exists(save_path):
            try:
                base, ext = os.path.splitext(save_path)
                counter = 1
                new_save_path = f"{base}-{counter}{ext}"
                while os.path.exists(new_save_path):
                    counter += 1
                    new_save_path = f"{base}-{counter}{ext}"
                os.rename(save_path, new_save_path)
            except Exception as e:
                logger.error(f"重命名旧头像失败: {e}")

        with open(save_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        avatar_db_url = f"avatars/{filename}"
        user.avatar = avatar_db_url
        user.save(update_fields=['avatar'])
        
        timestamp = int(timezone.now().timestamp())
        return f"{settings.MEDIA_URL}{avatar_db_url}?t={timestamp}"


class ForumService:
    @staticmethod
    def create_post(user, title, content):
        """创建新帖子"""
        post = Post(title=title, content=content, powner=user)
        post.save()
        return post

    @staticmethod
    def create_comment(user, post_id, content, comment_type, par_cid, root_cid):
        """创建新评论并更新帖子的最新评论时间"""
        par_cid = None if par_cid in [0, '0', ''] else par_cid
        root_cid = None if root_cid in [0, '0', ''] else root_cid
        post = Post.objects.get(pid=post_id)
        comment = Comment(
            content=content,
            cowner=user,
            comment_type=comment_type,
            post=post,
            parent_comment_id = par_cid,
            root_comment_id = root_cid,
        )
        comment.save()
        # 更新帖子的最新评论时间
        post.latest_comment_time = timezone.now()
        post.save(update_fields=['latest_comment_time'])
        return comment

    @staticmethod
    def get_posts(index_num, count=24):
        querys = Post.objects.filter(
            Q(latest_comment_time__isnull=False)
        ).select_related('powner').order_by('-latest_comment_time')[index_num : index_num + count]
        
        posts_list = []
        for post in querys:
            timestamp = int(time.time())
            avatar_url = None
            if post.powner.avatar:
                avatar_url = f"{post.powner.avatar.url}?v={timestamp}"
            else:
                avatar_url = f"{settings.MEDIA_URL}avatars/default.jpeg?v={timestamp}"
            posts_list.append({
                'pid': post.pid,
                'title': post.title,
                'content': post.content,
                'cover': post.cover_image.url if post.cover_image else None,
                'is_delete': bool(post.is_delete),
                'is_hidden': bool(post.is_hidden),
                'powner': {
                    'uid': post.powner.uid,
                    'name': post.powner.name,
                    'avatar_url': avatar_url if avatar_url else None,
                },
                'like_count': post.like_count,
                'create_time': post.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                'comment_count': post.comment_count,
            })
        return posts_list

    @staticmethod
    def get_comments(post_id, index_num, count=20):
        """获取评论列表并序列化"""
        querys = Comment.objects.filter(post_id=post_id,parent_comment_id__isnull=True,root_comment_id__isnull=True).select_related('cowner').order_by('cid')[index_num : index_num + count]
        comments_list = []
        for comment in querys:

            sub_querys = Comment.objects.filter(post_id=post_id,root_comment_id=comment.cid).select_related('cowner').order_by('cid')[0:2]
            sub_querys_count = Comment.objects.filter(post_id=post_id,root_comment_id=comment.cid).select_related('cowner').count()
            if sub_querys_count > 2:
                end = 0
            else:
                end = 1
            sub_comment_list = []
            for sub_comment in sub_querys:
                sub_comment_list.append({
                    'cid': sub_comment.cid,
                    'content': sub_comment.content,
                    'is_delete': bool(sub_comment.is_delete),
                    'parent_comment_id': sub_comment.parent_comment_id or -1,
                    'root_comment_id': sub_comment.root_comment_id or -1,
                    'cowner': {
                        'uid': sub_comment.cowner.uid,
                        'name': sub_comment.cowner.name,
                        'avatar_url': sub_comment.cowner.avatar.url if sub_comment.cowner.avatar else None,
                    },
                    'like_count': sub_comment.like_count,
                    'create_time': sub_comment.create_time.strftime("%Y-%m-%d %H:%M"),
                })


            comments_list.append({
                'cid': comment.cid,
                'content': comment.content,
                'is_delete': bool(comment.is_delete),
                'parent_comment_id': comment.parent_comment_id or -1,
                'root_comment_id': comment.root_comment_id or -1,
                'cowner': {
                    'uid': comment.cowner.uid,
                    'name': comment.cowner.name,
                    'avatar_url': comment.cowner.avatar.url if comment.cowner.avatar else None,
                },
                'like_count': comment.like_count,
                'create_time': comment.create_time.strftime("%Y-%m-%d %H:%M"),
                'sub_comments': sub_comment_list,
                'is_sub_comments_end': end,
            })
        return comments_list

    @staticmethod
    def get_sub_comments(post_id, root_cid, index_num, count=20):
        querys = Comment.objects.filter(post_id=post_id,root_comment_id=root_cid).select_related('cowner').order_by('cid')[index_num : index_num + count]
        sub_querys_count = Comment.objects.filter(post_id=post_id,root_comment_id=root_cid).select_related('cowner').count()
        end = 0
        if (index_num + count) > sub_querys_count:
            end = 1
        comments_list = []
        for comment in querys:
            comments_list.append({
                'cid': comment.cid,
                'content': comment.content,
                'is_delete': bool(comment.is_delete),
                'parent_comment_id': comment.parent_comment_id or -1,
                'root_comment_id': comment.root_comment_id or -1,
                'cowner': {
                    'uid': comment.cowner.uid,
                    'name': comment.cowner.name,
                    'avatar_url': comment.cowner.avatar.url if comment.cowner.avatar else None,
                },
                'like_count': comment.like_count,
                'create_time': comment.create_time.strftime("%Y-%m-%d %H:%M"),
                'is_sub_comments_end':end,
            })
        return comments_list

    @staticmethod
    def get_comment_like(post_id,user_id):
        querys = Comment_Like.objects.filter(post_id=post_id,user_id=user_id).values_list('comment_id',flat=True)
        like_cid_list = list(querys)
        return like_cid_list
        
        # querys = Comment_Like.objects.all()
        # like_cid_list = []
        # return like_cid_list
        # querys = Comment_Like.objects.filter(post_id=post_id,user_id=user_id).values_list('comment_id')
        # comment_ids = Comment_Like.objects.filter(
        #     post_id=post_id,     # 使用数据库列名 post_id
        #     user_id=user_id      # 使用数据库列名 user_id
        # ).values_list('comment_id', flat=True)
        
        

    @staticmethod
    def get_post_details(post_id):
        """获取单个帖子的详细信息并增加浏览量"""
        post = Post.objects.select_related('powner').get(pid=post_id)
        # 使用F表达式保证原子性操作，避免竞争条件
        Post.objects.filter(pid=post_id).update(view_count=F('view_count') + 1)
        return {
            'title': post.title,
            'content': post.content,
            'create_time': post.create_time.strftime("%Y-%m-%d %H:%M:%S"),
            'avatar_url': post.powner.avatar.url if post.powner.avatar else None,
        }

    @staticmethod
    def is_post_liked_by_user(post_id, user_id):
        """检查用户是否已点赞某帖子"""
        return Post_Like.objects.filter(post_id=post_id, user_id=user_id).exists()

    @staticmethod
    def is_comment_liked_by_user(post_id, user_id):
        """检查用户是否已点赞某帖子"""
        return Comment_Like.objects.filter(post_id=post_id, user_id=user_id).exists()

    @staticmethod
    @transaction.atomic
    def change_post_like_status(post_id, user_id):
        try:
            post = Post.objects.get(pid=post_id, is_delete=False)
        except Post.DoesNotExist:
            return False
        if Post_Like.objects.filter(post_id=post_id, user_id=user_id).exists():
            post.like_count = F('like_count') - 1
            post.save(update_fields=['like_count'])
            Post_Like.objects.filter(post_id=post_id, user_id=user_id).delete()
            return False
        else:
            post.like_count = F('like_count') + 1
            post.save(update_fields=['like_count'])
            Post_Like.objects.create(post_id=post_id, user_id=user_id)
            return True

    @staticmethod
    @transaction.atomic
    def change_comment_like_status(post_id, comment_id, user_id):
        try:
            comment = Comment.objects.get(cid=comment_id, is_delete=False)
        except Comment.DoesNotExist:
            return False
        if Comment_Like.objects.filter(comment_id=comment_id, user_id=user_id).exists():
            temp_count = comment.like_count
            comment.like_count = max(0, temp_count - 1)
            comment.save(update_fields=['like_count'])
            Comment_Like.objects.filter(comment_id=comment_id, user_id=user_id).delete()
            return False
        else:
            comment.like_count = F('like_count') + 1
            comment.save(update_fields=['like_count'])
            Comment_Like.objects.create(post_id=post_id, comment_id=comment_id, user_id=user_id)
            return True


    @staticmethod
    @transaction.atomic
    def ad_create_comment(user, post_id, comment_type, par_cid, root_cid):
        par_cid = None if par_cid in [0, '0', ''] else par_cid
        root_cid = None if root_cid in [0, '0', ''] else root_cid
        try:
            post = Post.objects.get(pid=post_id, is_delete=False)
            comments = Comment.objects.filter(
                post=post,
                is_delete=False
            ).select_related('cowner').order_by('create_time')
        except Post.DoesNotExist:
            return "errorCode 10001"


        powner_name = post.powner.name
        post_data_str = f"""
            帖子标题: {post.title}
            帖子作者: {powner_name}
            帖子内容:
            ---
            {post.content}
            ---
        """

        comments_data_str = "当前已有评论:\n"
        if comments.exists():
            for comment in comments:
                cowner_name = comment.cowner.name
                comments_data_str += f"- {cowner_name} 说: {comment.content}\n"
        else:
            comments_data_str += "（暂无评论）\n"

        prompt = f"""
        你是一个论坛的用户，你的任务是模拟一个真实人类，为下面的帖子写一条新的、有意义的评论。

        # 角色扮演指南:
        1.  **语气自然**: 像一个普通网友一样发言，可以按照权重选择基于以下任意一种风格发言:
            (1)普通语气,非常标准的回复方式,字句清楚表达到位,带有完整的标点符号;权重1
            (2)网友语气,表达比较口语化,通常不会带有完整的标点符号,通常使用空格符分隔,可能会带有逗号;权重5
            (3)网友语气,表达非常口语化,可以在表达中添加网络热梗,或者一些比较流行的内容;权重3
        2.  **内容相关**: 你的评论必须与帖子的内容或已有的评论紧密相关。
        3.  **避免重复**: 不要简单地重复帖子或其他评论的观点，尝试提出新的看法、问题或表示赞同/反对.
        4.  **简明扼要**: 评论不宜过长。

        # 帖子和已有评论的上下文:
        {post_data_str}
        {comments_data_str}

        # 你的任务:
        请根据以上内容，写一条新的评论。

        # 输出要求:
        请直接输出评论的文本内容，不要包含任何额外的话，例如 "好的，这是我的评论：" 等。
        """

        print(prompt)




        #kimi
        client = OpenAI(
            api_key = settings.OPENAI_KIMI_API_KEY,
            base_url = settings.OPENAI_KIMI_BASE_URL,
            timeout=120.0,
        )
        try:
            completion = client.chat.completions.create(
                model = "kimi-k2-thinking",
                messages = [
                    {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。"},
                    {"role": "user", "content": prompt}
                ],
                temperature = 0.6,
            )
            ai_comment_text = completion.choices[0].message.content.strip()
        except Exception as e:
            raise Exception(f"Kimi API 调用失败: {e}")
        print(ai_comment_text)
        

        comment = Comment(
            content=ai_comment_text,
            cowner=user,
            comment_type=comment_type,
            post=post,
            parent_comment_id = par_cid,
            root_comment_id = root_cid,
        )
        comment.save()
        post.latest_comment_time = timezone.now()
        post.save(update_fields=['latest_comment_time'])
        return comment

class JwtService:

    TOKEN_SECRET_KEY = settings.TOKEN_SECRET_KEY
    ALGORITHM = settings.JWT_CONFIG['ALGORITHM']
    ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_CONFIG['ACCESS_TOKEN_EXPIRE_MINUTES']

    @staticmethod
    def generate_token(user):
        payload = {
            'uid': user.uid,               # 用户唯一标识
            'account': user.account,
            'name': user.name,
            'exp': datetime.utcnow() + timedelta(minutes=JwtService.ACCESS_TOKEN_EXPIRE_MINUTES),
            'iat': datetime.utcnow(),
        }
        token = jwt.encode(payload, JwtService.TOKEN_SECRET_KEY, algorithm=JwtService.ALGORITHM)
        return token

    @staticmethod
    def verify_token(token):
        try:
            return jwt.decode(token, JwtService.TOKEN_SECRET_KEY, algorithms=[JwtService.ALGORITHM])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None
