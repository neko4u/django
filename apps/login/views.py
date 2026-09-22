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
from apps.captcha.services import verify_ticket
from apps.mailservice.codes import (
    drop_ticket,
    get_ticket,
    mask_email,
)
from .forms import (
    ChangePasswordByEmailForm,
    ChangePasswordByOldForm,
)



MAX_FAILED_ATTEMPTS = 5
LOCKOUT_TIME = 60 * 30

# 登录连续失败达到该次数后，后续登录必须先通过滑块验证（目前只在 frp 登录页生效）
SLIDER_TRIGGER_AFTER_FAILS = 2

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
    """frp 专用登录。

    与通用登录的区别：
      1. 成功后进入 frp 主页 findex（不是 index）
      2. 连续输错 SLIDER_TRIGGER_AFTER_FAILS 次后，必须通过滑块验证
    """
    template = 'frpServer/flogin.html'
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if request.session.get('is_logged_in'):
        if is_ajax:
            return JsonResponse({'success': True, 'redirect_url': reverse('findex')})
        return redirect('findex')

    if request.method == "GET":
        return render(request, template)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if not form.is_valid():
            error = "请输入正确的帐号或密码"
            if is_ajax:
                return JsonResponse({'success': False, 'error': error})
            return render(request, template, {'error': error})

        username = form.cleaned_data['user']
        password = form.cleaned_data['pwd']

        cache_key = f'login_fails_{username}'
        failed_attempts = cache.get(cache_key, 0)

        # 1) 锁定检查
        if failed_attempts >= MAX_FAILED_ATTEMPTS:
            ttl = cache.ttl(cache_key) or 0
            minutes = ttl // 60
            error = f'账户已被锁定，请等待 {minutes} 分钟后再试。'
            if is_ajax:
                return JsonResponse({'success': False, 'error': error})
            return render(request, template, {'error': error})

        # 2) 滑块检查（一次性消费，服务端说了算）
        if failed_attempts >= SLIDER_TRIGGER_AFTER_FAILS:
            slider_ok, slider_err = verify_ticket(request)
            if not slider_ok:
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'error': slider_err,
                        'need_slider': True,
                    })
                return render(request, template, {
                    'error': slider_err,
                    'need_slider': True,
                })

        # 3) 账号密码校验
        user = AuthenticationService.authenticate_user(username, password)

        if user:
            cache.delete(cache_key)
            request.session['is_logged_in'] = True
            request.session['info'] = AuthenticationService.login_session_data(user)
            request.session.modified = True
            if is_ajax:
                return JsonResponse({'success': True, 'redirect_url': reverse('findex')})
            return redirect('findex')

        new_attempts = failed_attempts + 1
        cache.set(cache_key, new_attempts, timeout=LOCKOUT_TIME)
        remaining = MAX_FAILED_ATTEMPTS - new_attempts
        error = f'帐号或密码错误，您还有 {remaining} 次尝试机会。'
        if remaining == 0:
            error = '帐号密码错误，帐号已锁定！'

        # 失败次数够了就把滑块弹出来，省得用户等下一次提交
        need_slider = new_attempts >= SLIDER_TRIGGER_AFTER_FAILS
        if is_ajax:
            return JsonResponse({
                'success': False,
                'error': error,
                'need_slider': need_slider,
            })
        return render(request, template, {'error': error, 'need_slider': need_slider})

    return render(request, template)




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
    """frp 专用注册：必须通过滑块验证，注册成功后去 frp 登录页。

    校验顺序刻意是「先表单、后滑块」：
    表单填错时不会消耗滑块 ticket，用户改完字段可以直接再提交，不用重新滑一次。
    """
    template = 'frpServer/fregister.html'
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    if request.method == "POST":
        form = RegisterForm(request.POST)

        if not form.is_valid():
            error = _first_form_error(form)
            if is_ajax:
                return JsonResponse({'success': False, 'error': error})
            return render(request, template, {'form': form, 'error': error})

        slider_ok, slider_err = verify_ticket(request)
        if not slider_ok:
            if is_ajax:
                return JsonResponse({'success': False, 'error': slider_err})
            return render(request, template, {'form': form, 'error': slider_err})

        AuthenticationService.register_user(form)
        if is_ajax:
            return JsonResponse({'success': True, 'redirect_url': reverse('flogin')})
        messages.success(request, "注册成功，请登录！")
        return redirect('flogin')

    return render(request, template, {'form': RegisterForm()})


def _first_form_error(form):
    """取第一条表单错误，用于直接展示给用户"""
    for errors in form.errors.values():
        for error in errors:
            return str(error)
    return '请检查填写的内容'


def _email_ticket_ok(request, expected_email, scene='change_email'):
    """校验「改邮箱」用的邮箱验证码 ticket。

    ticket 是绑定邮箱的，必须和当前账号的旧邮箱一致，
    防止拿别人邮箱的 ticket 来改自己的邮箱。
    """
    ticket = (request.POST.get('email_ticket') or '').strip()
    payload = get_ticket(ticket, scene)
    if not payload:
        return False, '请先获取并填写旧邮箱的验证码'
    if (payload.get('email') or '').strip().lower() != (expected_email or '').strip().lower():
        return False, '邮箱验证信息与当前账号不匹配，请重新验证'
    return True, ''


@login_required_view
def modify_info(request, mode='general'):
    """修改资料。

    mode='frp' ：需要滑块验证；改邮箱还要额外过旧邮箱验证码；保存后回 findex。
    mode='general'：保持原有行为（通用页面等后续指令再切）。
    """
    is_frp = (mode == 'frp')
    home_url = reverse('findex') if is_frp else reverse('index')
    login_name = 'flogin' if is_frp else 'login'
    template = 'login/modify_info.html'

    try:
        user_instance = UserInfo.objects.get(uid=request.session['info']['uid'])
    except UserInfo.DoesNotExist:
        messages.error(request, "用户不存在，请重新登录。")
        return redirect(login_name)

    # 重要：原邮箱必须在表单校验之前记下来。
    # 原因：ModelForm._post_clean() 会把 cleaned_data 写回 self.instance，
    # 一旦 form.is_valid() 跑过，user_instance.email 就已经变成**新邮箱**了，
    # 后面再拿它去和验证码 ticket 里的邮箱比对，必然"不匹配"，改邮箱流程会卡死。
    original_email = user_instance.email or ''

    context = {
        'is_frp': is_frp,
        'home_url': home_url,
        'account_email': original_email,
        'masked_email': mask_email(original_email),
    }

    if request.method == "POST":
        form = ModifyInfoForm(request.POST, instance=user_instance, user=user_instance)
        context['form'] = form

        # 1) 表单本身先过（不过就返回，顺带省下一次滑块）
        if not form.is_valid():
            messages.error(request, _first_form_error(form))
            return render(request, template, context)

        email_changed = form.email_changed()

        if is_frp:
            # 2) 改邮箱 -> 先验旧邮箱验证码（不动滑块 ticket，避免白白消耗一次）
            if email_changed:
                ok, err = _email_ticket_ok(request, original_email)
                if not ok:
                    messages.error(request, err)
                    return render(request, template, context)

            # 3) 滑块验证（frp 版必过，一次性消费）
            slider_ok, slider_err = verify_ticket(request)
            if not slider_ok:
                messages.error(request, slider_err)
                return render(request, template, context)

            if email_changed:
                drop_ticket((request.POST.get('email_ticket') or '').strip())

        form.save()
        # 更新 session 中的昵称
        request.session['info']['userName'] = form.cleaned_data['name']
        request.session.modified = True
        messages.success(request, "信息修改成功！")
        return redirect(home_url)

    context['form'] = ModifyInfoForm(instance=user_instance, user=user_instance)
    return render(request, template, context)


def change_password(request, mode='general', scope='logged'):
    """修改密码 / 找回密码（frp 与通用版共用这一套视图和模板）。

    两种方式：
      flow=old   —— 记得原密码，输入旧密码 + 新密码（要求已登录）
      flow=email —— 邮箱验证码验证后设置新密码（未登录也能用，即"找回密码"）

    两条路径都必须先通过滑块验证。
    """
    is_frp = (mode == 'frp')
    is_anonymous_entry = (scope == 'anonymous')

    back_url = reverse('flogin') if is_frp else reverse('login')
    home_url = reverse('findex') if is_frp else reverse('index')
    template = 'login/change_password.html'

    user = None
    if request.session.get('is_logged_in'):
        user = UserInfo.objects.filter(
            uid=(request.session.get('info') or {}).get('uid')
        ).first()

    # scope='logged' 的入口必须登录
    if not is_anonymous_entry and not user:
        return redirect(back_url)

    active_tab = 'email' if (not user or is_anonymous_entry) else 'old'
    form_error = ''

    if request.method == 'POST':
        flow = (request.POST.get('flow') or 'old').strip()
        if not user:
            # 未登录时只能走邮箱验证码
            flow = 'email'
        active_tab = 'email' if flow == 'email' else 'old'

        if flow == 'old':
            form = ChangePasswordByOldForm(request.POST)
            if not form.is_valid():
                form_error = _first_form_error(form)
            elif not AuthenticationService.verify_password(
                    user, form.cleaned_data['old_pwd']):
                form_error = '原密码不正确'
            else:
                slider_ok, slider_err = verify_ticket(request)
                if not slider_ok:
                    form_error = slider_err
                else:
                    AuthenticationService.change_password(
                        user, form.cleaned_data['new_pwd'])
                    request.session.flush()
                    messages.success(request, '密码修改成功，请使用新密码重新登录')
                    return redirect(back_url)
        else:
            form = ChangePasswordByEmailForm(request.POST)
            email_ticket = (request.POST.get('email_ticket') or '').strip()
            payload = get_ticket(email_ticket, 'change_pwd')

            if not form.is_valid():
                form_error = _first_form_error(form)
            elif not payload:
                form_error = '邮箱验证已失效，请重新获取验证码'
            else:
                ticket_email = (payload.get('email') or '').strip()
                target = user

                if target is None:
                    qs = AuthenticationService.find_users_by_email(ticket_email)
                    if qs.count() > 1:
                        form_error = '该邮箱绑定了多个账号，请联系管理员处理'
                    else:
                        target = qs.first()

                if not form_error and target is None:
                    form_error = '账号不存在，请联系管理员'
                elif not form_error and user is not None and \
                        (user.email or '').strip().lower() != ticket_email.lower():
                    form_error = '邮箱验证信息与当前账号不匹配'
                elif not form_error:
                    slider_ok, slider_err = verify_ticket(request)
                    if not slider_ok:
                        form_error = slider_err
                    else:
                        AuthenticationService.change_password(
                            target, form.cleaned_data['new_pwd'])
                        drop_ticket(email_ticket)
                        request.session.flush()
                        messages.success(request, '密码已重置，请使用新密码登录')
                        return redirect(back_url)

    return render(request, template, {
        'is_frp': is_frp,
        'is_anonymous': not user,
        'account_email': (user.email or '') if user else '',
        'masked_email': mask_email((user.email or '') if user else ''),
        'back_url': back_url,
        'home_url': home_url,
        'active_tab': active_tab,
        'form_error': form_error,
    })

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