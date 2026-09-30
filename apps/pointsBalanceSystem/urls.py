from django.urls import path
from . import views
from . import signin_views

app_name = 'pointsBalanceSystem'

urlpatterns = [
    path('', views.exchange_list_view, name='exchange_list'),
    path('exchange/',views.exchange_list_view,name='exchange_list'),
    path('exchange/detail/',views.exchange_detail_view,name='exchange_detail'),
    # 签到接口（findex 页面「获取积分 / 参与签到」用）
    path('api/sign-in/status/', signin_views.sign_in_status, name='sign_in_status'),
    path('api/sign-in/', signin_views.sign_in, name='sign_in'),
]
