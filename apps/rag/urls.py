from django.urls import path

from . import views

app_name = 'rag'

urlpatterns = [
    path('', views.wiki_page, name='wiki_page'),
    path('api/ask/', views.ask_stream, name='ask_stream'),
    path('api/feedback/', views.feedback, name='feedback'),
]
