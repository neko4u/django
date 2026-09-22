# apps/mailservice/urls.py
# 在 project1/urls.py 里用 path('api/', include('apps.mailservice.urls')) 挂载
# 最终地址：/api/send-email-code/  /api/verify-email-code/  /api/check-email-ticket/
from django.urls import path

from . import views

urlpatterns = [
    path('send-email-code/', views.send_email_code, name='send_email_code'),
    path('verify-email-code/', views.verify_email_code, name='verify_email_code'),
    path('check-email-ticket/', views.check_email_ticket, name='check_email_ticket'),
]
