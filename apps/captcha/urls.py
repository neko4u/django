from django.urls import path

from . import views

urlpatterns = [
    path('slider-captcha/', views.slider_captcha, name='slider_captcha'),
    path('verify-slider/', views.verify_slider, name='verify_slider'),
]
