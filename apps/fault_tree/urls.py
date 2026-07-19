from django.urls import path
from . import views

app_name = 'fault_tree'

urlpatterns = [
    # 页面
    path('', views.index, name='index'),

    # 权限查询
    path('api/permission/', views.api_permission, name='api_permission'),

    # Manual
    path('api/manuals/', views.api_list_manuals, name='api_list_manuals'),
    path('api/manuals/create/', views.api_create_manual, name='api_create_manual'),
    path('api/manuals/<int:manual_id>/delete/', views.api_delete_manual, name='api_delete_manual'),

    # Doc
    path('api/docs/', views.api_list_docs, name='api_list_docs'),
    path('api/docs/search/', views.api_search_docs, name='api_search_docs'),
    path('api/docs/create/', views.api_create_doc, name='api_create_doc'),
    path('api/docs/<int:doc_id>/update/', views.api_update_doc, name='api_update_doc'),
    path('api/docs/<int:doc_id>/delete/', views.api_delete_doc, name='api_delete_doc'),
    path('api/docs/<int:doc_id>/graph/', views.api_get_doc_graph, name='api_get_doc_graph'),

    # Node
    path('api/nodes/', views.api_list_nodes, name='api_list_nodes'),
    path('api/nodes/<int:node_id>/', views.api_get_node, name='api_get_node'),
    path('api/nodes/create/', views.api_create_node, name='api_create_node'),
    path('api/nodes/<int:node_id>/update/', views.api_update_node, name='api_update_node'),
    path('api/nodes/<int:node_id>/delete/', views.api_delete_node, name='api_delete_node'),

    # Edge
    path('api/edges/', views.api_list_edges, name='api_list_edges'),
    path('api/edges/create/', views.api_create_edge, name='api_create_edge'),
    path('api/edges/<int:edge_id>/update/', views.api_update_edge, name='api_update_edge'),
    path('api/edges/<int:edge_id>/delete/', views.api_delete_edge, name='api_delete_edge'),

    # Category
    path('api/categories/', views.api_list_categories, name='api_list_categories'),
    path('api/categories/create/', views.api_create_category, name='api_create_category'),

    # Comment
    path('api/comments/', views.api_list_comments, name='api_list_comments'),
    path('api/comments/create/', views.api_create_comment, name='api_create_comment'),

    # 图片上传
    path('api/upload/image/', views.api_upload_image, name='api_upload_image'),
]
