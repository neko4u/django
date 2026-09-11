from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.messages import get_messages
from .forms import LoginForm, RegisterForm, ModifyInfoForm
from .services import AuthenticationService, AvatarService, ForumService, JwtService
from .decorators import login_required_view, login_required_api
from .models import UserInfo, Post
from django.http import HttpResponse
import logging
import traceback
from django.contrib.auth import authenticate, login
from django.core.cache import cache
from django.conf import settings
from .models import CommentGenerationTask
import json
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from apps.pointsBalanceSystem.models import PointExchangeActivity, UserPoint
from apps.pointsBalanceSystem.forms import ExchangeFRPForm


MAX_FAILED_ATTEMPTS = 5
LOCKOUT_TIME = 60 * 30
redis_client = cache.client.get_client()

logger = logging.getLogger(__name__)

# --- 用户认证与页面视图 ---

def user_login(request):
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if request.session.get('is_logged_in'):
        if is_ajax:
            return JsonResponse({'success': True, 'redirect_url': reverse('index')})
        return redirect('index')

    if request.method == "GET":
        return render(request, 'login/login.html')

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['user']
            password = form.cleaned_data['pwd']
            # user = AuthenticationService.authenticate_user(
            #     form.cleaned_data['user'],
            #     form.cleaned_data['pwd']
            # )

            cache_key = f'login_fails_{username}'
            failed_attempts = cache.get(cache_key, 0)
            if failed_attempts >= MAX_FAILED_ATTEMPTS:
                ttl = cache.ttl(cache_key) or 0
                minutes = ttl // 60
                error = f'账户已被锁定，请等待 {minutes} 分钟后再试。'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error})
                return render(request, 'login/login.html', {'error': error})
            user = AuthenticationService.authenticate_user(username, password)

            if user:
                cache.delete(cache_key)
                request.session['is_logged_in'] = True
                request.session['info'] = AuthenticationService.login_session_data(user)
                request.session.modified = True
                if is_ajax:
                    return JsonResponse({'success': True, 'redirect_url': reverse('index')})
                return redirect('index')
            else:
                new_attempts = failed_attempts + 1
                cache.set(cache_key, new_attempts, timeout=LOCKOUT_TIME)
                remaining = MAX_FAILED_ATTEMPTS - new_attempts
                error = f'帐号或密码错误，您还有 {remaining} 次尝试机会。'
                if (remaining == 0):
                    error = '帐号密码错误，帐号已锁定！'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error})
                return render(request, 'login/login.html', {'error': error})
        else:
            return render(request, 'login/login.html',{'error': "请输入正确的帐号或密码"})
        
    
    return render(request, 'login/login.html')

def frp_user_login(request):
    # 0911新增,用于frp登录,重定向到frp主页
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if request.session.get('is_logged_in'):
        if is_ajax:
            return JsonResponse({'success': True, 'redirect_url': reverse('index')})
        return redirect('findex')

    if request.method == "GET":
        return render(request, 'frpServer/flogin.html')

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['user']
            password = form.cleaned_data['pwd']
            # user = AuthenticationService.authenticate_user(
            #     form.cleaned_data['user'],
            #     form.cleaned_data['pwd']
            # )

            cache_key = f'login_fails_{username}'
            failed_attempts = cache.get(cache_key, 0)
            if failed_attempts >= MAX_FAILED_ATTEMPTS:
                ttl = cache.ttl(cache_key) or 0
                minutes = ttl // 60
                error = f'账户已被锁定，请等待 {minutes} 分钟后再试。'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error})
                return render(request, 'frpServer/flogin.html', {'error': error})
            user = AuthenticationService.authenticate_user(username, password)

            if user:
                cache.delete(cache_key)
                request.session['is_logged_in'] = True
                request.session['info'] = AuthenticationService.login_session_data(user)
                request.session.modified = True
                if is_ajax:
                    return JsonResponse({'success': True, 'redirect_url': reverse('index')})
                return redirect('index')
            else:
                new_attempts = failed_attempts + 1
                cache.set(cache_key, new_attempts, timeout=LOCKOUT_TIME)
                remaining = MAX_FAILED_ATTEMPTS - new_attempts
                error = f'帐号或密码错误，您还有 {remaining} 次尝试机会。'
                if (remaining == 0):
                    error = '帐号密码错误，帐号已锁定！'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error})
                return render(request, 'frpServer/flogin.html', {'error': error})
        else:
            return render(request, 'frpServer/flogin.html',{'error': "请输入正确的帐号或密码"})
        
    
    return render(request, 'frpServer/flogin.html')



def user_logout(request):
    request.session.flush()
    return redirect('login')

def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        # form = RegisterForm(request.POST, request.FILES)
        if form.is_valid():
            AuthenticationService.register_user(form)
            messages.success(request, "注册成功，请登录！")
            return redirect('login')
    else:
        form = RegisterForm()
    return render(request, 'login/register.html', {'form': form})

def frp_register(request):
    # 0911新增方法,用于frp推广注册
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            AuthenticationService.register_user(form)
            messages.success(request, "注册成功，请登录！")
            return redirect('flogin')
    else:
        form = RegisterForm()
    return render(request, 'frpServer/fregister.html', {'form': form})

@login_required_view
def modify_info(request):
    try:
        user_instance = UserInfo.objects.get(uid=request.session['info']['uid'])
    except UserInfo.DoesNotExist:
        messages.error(request, "用户不存在，请重新登录。")
        return redirect('login')

    if request.method == "POST":
        form = ModifyInfoForm(request.POST, instance=user_instance)
        if form.is_valid():
            form.save()
            # 更新session中的昵称等信息
            request.session['info']['userName'] = form.cleaned_data['name']
            request.session.modified = True
            messages.success(request, "信息修改成功！")
            return redirect('index')
    else:
        form = ModifyInfoForm(instance=user_instance)
    
    return render(request, 'login/modify_info.html', {'form': form})

# --- 基本页面 ---

@login_required_view
def index(request):
    return render(request, 'login/index.html')


#  ------ frp 主页,兑换活动固定2
FINDEX_EXCHANGE_AID = 2
@login_required_view
def findex(request):
    context = {}

    uid = (request.session.get('info') or {}).get('uid')
    user = UserInfo.objects.filter(uid=uid).first() if uid else None

    if user:
        # 只取启用中的活动；取不到时模板显示占位文案，不会 404
        activity = (
            PointExchangeActivity.objects
            .filter(pk=FINDEX_EXCHANGE_AID, enable=True)
            .first()
        )

        points_balance = 0
        user_point = UserPoint.objects.filter(user=user).first()
        if user_point and user_point.enable:
            points_balance = user_point.points_balance

        context.update({
            'activity': activity,
            'points_balance': points_balance,
            'form': ExchangeFRPForm(user=user, activity=activity),
        })

    return render(request, 'frpServer/findex.html', context)

@login_required_view
def home(request):
    return render(request, 'login/home.html')

@login_required_view
def page1(request):
    return render(request, 'login/page1.html')

@login_required_view
def forumIndex(request):
    return render(request, 'login/forumIndex.html')

@login_required_view
def post_page(request):
    pid = request.GET.get("pid")
    if not pid:
        messages.error(request, "未提供帖子ID。")
        return redirect('forumIndex')
    try:
        post = Post.objects.get(pid=pid)
        return render(request, 'login/page.html', {'post': post})
    except Post.DoesNotExist:
        messages.error(request, "帖子不存在。")
        return redirect('forumIndex')




@login_required_api
def uploadAvatar(request):
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "需要POST请求"}, status=405)
    
    file = request.FILES.get("avatar")
    if not file:
        return JsonResponse({"status": "error", "message": "未选择文件"}, status=400)
        
    try:
        user = UserInfo.objects.get(uid=request.session['info']['uid'])
        new_avatar_url = AvatarService.handle_avatar_upload(user, file)
        # 更新session中的头像URL
        request.session['info']['avatar'] = new_avatar_url
        request.session.modified = True
        
        return JsonResponse({"status": "success", "url": new_avatar_url, "message": "头像上传成功"})
    except UserInfo.DoesNotExist:
        return JsonResponse({"status": "error", "message": "用户认证信息失效"}, status=401)
    except ValueError as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    except Exception as e:
        logger.error(f"头像上传时发生未处理的异常: {e}\n{traceback.format_exc()}")
        return JsonResponse({"status": "error", "message": "服务器内部错误"}, status=500)

@login_required_api
def create_post(request):
    if request.method == 'POST':
        user = UserInfo.objects.get(uid=request.session['info']['uid'])
        title = request.POST.get("title", "").strip()
        content = request.POST.get("content", "").strip()
        if not title or not content:
            return JsonResponse({'status': 'error', 'message': '标题和内容不能为空'}, status=400)
        
        ForumService.create_post(user=user, title=title, content=content)
        return JsonResponse({'status': 'success', 'message': '发布成功'})
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def create_comment(request):
    if request.method == 'POST':
        user = UserInfo.objects.get(uid=request.session['info']['uid'])
        content = request.POST.get("content", "").strip()
        ctype = request.POST.get("comment_type")
        pid = request.POST.get("pid")
        par_cid = request.POST.get("par_cid")
        root_cid = request.POST.get("root_cid")

        if not all([user, content, ctype, pid]):
            return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)

        ForumService.create_comment(user=user, post_id=pid, content=content, comment_type=ctype,par_cid=par_cid,root_cid=root_cid)
        return JsonResponse({'status': 'success', 'message': '评论成功'})
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def query_posts(request):
    if request.method == 'POST':
        try:
            index_num = int(request.POST.get("indexNum", 0))
            posts_list = ForumService.get_posts(index_num)
            return JsonResponse(posts_list, safe=False)
        except Exception as e:
            logger.error(f"查询帖子时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def query_comments(request):
    if request.method == 'POST':
        try:
            pid = request.POST.get("pid")
            uid = request.session["info"]["uid"]
            index_num = int(request.POST.get("indexNum", 0))
            if not pid:
                return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
            
            comments_list = ForumService.get_comments(pid, index_num)
            liked_comment_list = ForumService.get_comment_like(pid,uid)
            data = {
                'comments_list' : comments_list,
                'liked_comment_cid' : liked_comment_list,
            }
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error(f"查询评论时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def query_sub_comments(request):
    if request.method == 'POST':
        try:
            pid = request.POST.get("pid")
            uid = request.session["info"]["uid"]
            par_cid = request.POST.get("par_cid")
            root_cid = request.POST.get("root_cid")
            index_num = int(request.POST.get("sub_indexNum", 0))
            if not pid:
                return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
            
            comments_list = ForumService.get_sub_comments(pid,root_cid,index_num)
            liked_comment_list = ForumService.get_comment_like(pid,uid)
            data = {
                'sub_comments_list' : comments_list,
                # 'liked_comment_cid' : liked_comment_list,
            }
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error(f"查询评论时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def get_post_detail(request):
    if request.method == 'POST':
        pid = request.POST.get("pid")
        if not pid:
            return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
        try:
            post_details = ForumService.get_post_details(pid)
            return JsonResponse({'status': 'success', 'post': post_details})
        except Post.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '帖子不存在'}, status=404)
        except Exception as e:
            logger.error(f"获取帖子详情时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def get_post_like(request):
    # 渲染post点赞状态
    if request.method == "POST":
        try:
            pid = request.POST.get("pid")
            uid = request.session["info"]["uid"]
            if not pid:
                return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
            
            is_liked = ForumService.is_post_liked_by_user(post_id=pid, user_id=uid)
            return JsonResponse({'status': 'success', 'is_liked': is_liked})
        except Exception as e:
            logger.error(f"获取点赞状态时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def do_post_like(request):
    #    获取点赞状态,点赞或者取消点赞   post
    if request.method == "POST":
        try:
            pid = request.POST.get("pid")
            uid = request.session["info"]["uid"]
            if not pid:
                return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
            temp = ForumService.change_post_like_status(post_id=pid, user_id=uid) 
            # ↑  1点赞,0取消点赞
            return JsonResponse({'status': 'success', 'do_like': temp})
        except Exception as e:
            logger.error(f"点赞时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def do_comment_like(request):
    #    获取点赞状态,点赞或者取消点赞   comment
    if request.method == "POST":
        try:
            cid = request.POST.get("cid")
            pid = request.POST.get("pid")
            uid = request.session["info"]["uid"]
            if not pid:
                return JsonResponse({'status': 'error', 'message': '缺少帖子ID'}, status=400)
            if not cid:
                return JsonResponse({'status': 'error', 'message': '缺少评论ID'}, status=400)
            temp = ForumService.change_comment_like_status(post_id=pid, comment_id=cid, user_id=uid) 
            # ↑  1点赞,0取消点赞
            return JsonResponse({'status': 'success', 'do_like': temp})
        except Exception as e:
            logger.error(f"点赞时发生未处理的异常: {e}\n{traceback.format_exc()}")
            return JsonResponse({'status': 'error', 'message': '服务器内部错误'}, status=500)
    return JsonResponse({'status': 'error', 'message': '需要POST请求'}, status=405)

@login_required_api
def admin_panel(request):
    if request.method == "POST":
        return render(request, 'suadmin/adminIndex.html')
    if request.method == "GET":
        return render(request, 'suadmin/adminIndex.html')

@login_required_api
def ad_create_comment(request):
    if request.method == "POST":
        pid = request.POST.get("pid")
        num = request.POST.get("num",1)
        author_uid = request.POST.get("author_uid", 10064)
        try:
            num = int(num)
            pid = int(pid)
            author_uid = int(author_uid)
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': '参数格式错误'}, status=400)

        try:
            author = UserInfo.objects.get(uid=author_uid)
        except UserInfo.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '作者用户不存在'}, status=400)

        try:
            operator_uid = request.session["info"]["uid"]
            operator = UserInfo.objects.get(uid=operator_uid)
        except UserInfo.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '操作者用户不存在'}, status=400)
        # user = UserInfo.objects.get(uid=10064)
        # ctype = 1
        # root_cid = -1
        # par_cid = -1

        task = CommentGenerationTask.objects.create(
            operator=operator,
            author=author,
            pid=pid,
            num=num,
            status='pending'
        )
        redis_client = cache.client.get_client()
        redis_client.lpush('task:comment_queue', str(task.id))

        return JsonResponse({
            'status': 'success',
            'task_id': str(task.id),
            'message': '任务已提交，请稍后查看结果'
        })



    
    # content = request.POST.get("content", "").strip()
    # pid = request.POST.get("pid")
    # par_cid = request.POST.get("par_cid")
    # root_cid = request.POST.get("root_cid")
    # if not all([user, ctype, pid]):
    #     return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)
    # print("准备传输")
    # ForumService.ad_create_comment(user=user, post_id=pid, comment_type=ctype,par_cid=par_cid,root_cid=root_cid)
    # print("传输完成")
    # return JsonResponse({'status': 'success', 'message': '评论成功'})

@login_required_api
def task_list_api(request):
    tasks = CommentGenerationTask.objects.all()[:50]  # 限制条数
    data = []
    for task in tasks:
        data.append({
            'id': str(task.id),
            'pid': task.pid,
            'num': task.num,
            'status': task.status,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'result': task.result,
        })
    return JsonResponse({'tasks': data})

@csrf_exempt
def user_token_login(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['user']
            password = form.cleaned_data['pwd']

            cache_key = f'login_fails_{username}'
            failed_attempts = cache.get(cache_key, 0)
            if failed_attempts >= MAX_FAILED_ATTEMPTS:
                ttl = cache.ttl(cache_key) or 0
                minutes = ttl // 60
                error = f'账户已被锁定，请等待 {minutes} 分钟后再试。'
                return JsonResponse({
                    'code': 1,
                    'message': error,
                }, status=403)
            user = AuthenticationService.authenticate_user(username, password)

            if user:
                cache.delete(cache_key)
                token = JwtService.generate_token(user)
                expires_in = JwtService.ACCESS_TOKEN_EXPIRE_MINUTES * 60
                # 传秒
                return JsonResponse({
                    'code': 0,
                    'message': '登录成功',
                    'token': token,
                    'expires_in': expires_in,
                })
            else:
                new_attempts = failed_attempts + 1
                cache.set(cache_key, new_attempts, timeout=LOCKOUT_TIME)
                remaining = MAX_FAILED_ATTEMPTS - new_attempts
                error = f'帐号或密码错误，您还有 {remaining} 次尝试机会。'
                return JsonResponse({
                    'code': 1,
                    'message': error,
                }, status=401)
        else:
            return JsonResponse({
                'code': 1,
                'message': '请输入正确的帐号或密码',
            }, status=400)
    return JsonResponse({'code': 1, 'message': '仅支持 POST 请求'}, status=405)