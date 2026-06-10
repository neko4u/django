from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_page, name='chat_page'),
    path('new/', views.new_conversation, name='chat_new'),
    path('list/', views.list_conversations, name='chat_list'),
    path('<int:conversation_id>/send/', views.send_message, name='chat_send'),
    path('<int:conversation_id>/messages/', views.get_messages, name='chat_messages'),
    path('<int:conversation_id>/rename/', views.rename_conversation, name='chat_rename'),
    path('<int:conversation_id>/delete/', views.delete_conversation, name='chat_delete'),
    path('<int:conversation_id>/config/', views.get_config, name='chat_get_config'),
    path('<int:conversation_id>/config/update/', views.update_config, name='chat_update_config'),
    path('stop/', views.stop_generation, name='chat_stop'),
    path('<int:conversation_id>/generate_title/', views.generate_title, name='chat_generate_title'),
    path('admin/tasks/', views.admin_tasks_page, name='admin_tasks_page'),
    path('admin/tasks/data/', views.admin_tasks_data, name='admin_tasks_data'),
    path('permissions/', views.get_permissions, name='chat_permissions'),
    path('models/', views.get_models, name='chat_models'),
    path('web_search_check/', views.web_search_check, name='web_search_check'),
    path('tavily_search_check/', views.tavily_search_check, name='tavily_search_check'),
    path('tool_calls_check/', views.tool_calls_check, name='tool_calls_check'),
    path('tool_call_check/', views.tool_call_check, name='tool_call_check'),
]