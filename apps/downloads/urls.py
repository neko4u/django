# apps/downloads/urls.py
# 在 project1/urls.py 里用 path('download/', include('apps.downloads.urls')) 挂载
# 最终地址：/download/file/  —— 点击即下载（按 IP 限流，限流对客户端不可见）

from django.urls import path

from . import views

urlpatterns = [
    path('file/', views.download_file, name='download_file'),
]
