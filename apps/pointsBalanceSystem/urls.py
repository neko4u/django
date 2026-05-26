from django.urls import path
from . import views

app_name = 'pointsBalanceSystem'

urlpatterns = [
    path('', views.exchange_list_view, name='exchange_list'),
    path('exchange/',views.exchange_list_view,name='exchange_list'),
    path('exchange/detail/',views.exchange_detail_view,name='exchange_detail'),
]