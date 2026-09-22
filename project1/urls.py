"""project1 URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from apps.login import views as login_views
from apps.frpServer import views as frpServer_views
from django.views.generic import RedirectView
from django.urls import include
from apps.llm_chat import views as chat_views
# from django.views.static import serve
# from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', login_views.user_login,name="login"),
    path('token_login/', login_views.user_token_login,name="user_token_login"),
    path('logout/', login_views.user_logout, name='logout'),
    path('index/', login_views.index,name="index"),
    path('home/', login_views.index,name="index"),
    path('page1/', login_views.page1,name="page1"),
    path('register/', login_views.register,name="register"),
    path('modify_info/', login_views.modify_info,name="modify_info"),
    path('uploadAvatar/', login_views.uploadAvatar,name="uploadAvatar"),
    path('forumIndex/', login_views.forumIndex,name="forumIndex"),
    path('create_post/', login_views.create_post,name="create_post"),
    path('create_comment/', login_views.create_comment,name="create_comment"),
    path('query_posts/', login_views.query_posts,name="query_posts"),
    path('query_comments/',login_views.query_comments,name="query_comments"),
    path('query_sub_comments/',login_views.query_sub_comments,name="query_sub_comments"),
    path('get_post_detail/',login_views.get_post_detail,name="get_post_detail"),
    path('forumIndex/page/',login_views.post_page,name="post_page"),
    path('get_post_like/',login_views.get_post_like,name="get_post_like"),
    path('do_post_like/',login_views.do_post_like,name="do_post_like"),
    path('do_comment_like/',login_views.do_comment_like,name="do_comment_like"),
    # admin
    path('suadmin/',login_views.admin_panel,name="admin_panel"),
    path('ad_create_comment/',login_views.ad_create_comment,name="ad_create_comment"),
    path('task-list-api/', login_views.task_list_api, name='task_list_api'),
    # frp
        # frp_user_index : 同主页,限制访问内容
    path('findex/', login_views.findex, name='findex'),
    path('flogin/', login_views.frp_user_login, name='flogin'),
    path('fregister/', login_views.frp_register, name='fregister'),
    path('flogout/', login_views.user_logout, {'mode': 'frp'}, name='flogout'),
        # frp 版修改资料 / 修改密码
    path('fmodify_info/', login_views.modify_info,
         {'mode': 'frp'}, name='fmodify_info'),
    path('fchange_password/', login_views.change_password,
         {'mode': 'frp', 'scope': 'logged'}, name='fchange_password'),
        # 通用版修改密码 / 找回密码（与 frp 版共用同一个视图和模板）
    path('change_password/', login_views.change_password,
         {'mode': 'general', 'scope': 'logged'}, name='change_password'),
    path('forgot_password/', login_views.change_password,
         {'mode': 'general', 'scope': 'anonymous'}, name='forgot_password'),
    path('fforgot_password/', login_views.change_password,
         {'mode': 'frp', 'scope': 'anonymous'}, name='fforgot_password'),
    path('manage/', frpServer_views.frp_index, name='frp_manage'),
    path('api/start/', frpServer_views.api_frp_start, name='frp_api_start'),
    path('api/stop/', frpServer_views.api_frp_stop, name='frp_api_stop'),
    path('api/restart/', frpServer_views.api_frp_restart, name='frp_api_restart'),
    path('api/update_token/', frpServer_views.api_frp_update_token, name='frp_api_update_token'),
    path('api/status/', frpServer_views.api_frp_status_json, name='frp_api_status'),
    path('api/FrpToken',frpServer_views.FrpToken,name='FrpToken'),
    # frp 会话计费（FrpClient 调用）
    path('api/frp_session/start/', frpServer_views.api_frp_session_start, name='frp_session_start'),
    path('api/frp_session/heartbeat/', frpServer_views.api_frp_session_heartbeat, name='frp_session_heartbeat'),
    path('api/frp_session/stop/', frpServer_views.api_frp_session_stop, name='frp_session_stop'),
    path('api/frp_session/status/', frpServer_views.api_frp_session_status, name='frp_session_status'),
    # 远程端口租赁（FrpClient 调用）
    path('api/frp_port/allocate/', frpServer_views.api_frp_port_allocate, name='frp_port_allocate'),
    path('api/frp_port/release/', frpServer_views.api_frp_port_release, name='frp_port_release'),
    path('api/frp_port/', frpServer_views.api_frp_port_current, name='frp_port_current'),
    path('api/user_profile/', frpServer_views.api_user_profile, name='user_profile'),
    #pointsBalanceSystem
    path('points/', include('apps.pointsBalanceSystem.urls', namespace='points')),# 滑块验证码接口 /api/slider-captcha/  /api/verify-slider/
    path('api/', include('apps.captcha.urls')),# 邮箱验证码接口 /api/send-email-code/  /api/verify-email-code/
    path('api/', include('apps.mailservice.urls')),

    #llm_chat
    path('chat/', include('apps.llm_chat.urls')),
    #ft
    path('fault-tree/', include('apps.fault_tree.urls')),
    #default
    path('', RedirectView.as_view(url='/login/')),
]

