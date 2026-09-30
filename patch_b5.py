# 批⑤ 补丁：doc_save 注入锚点 id + 前台路由
#   ⚠️ 幂等：重复运行不会重复插入（第二、三次运行会显示"已经是目标状态"）
#   在仓库根目录执行：  ./venv38/bin/python patch_b5.py
import io

TARGETS = [
    ('apps/helpdocs/admin_views.py', [
        # ① 导入 inject_heading_ids
        ("from .models import HelpCenterDoc\n"
         "from .sanitize import clean_html, html_to_markdown",
         "from .models import HelpCenterDoc\n"
         "from .sanitize import clean_html, html_to_markdown\n"
         "from .toc import inject_heading_ids"),

        # ② doc_save 里注入锚点
        ("    safe_html = clean_html(raw_html)\n"
         "    markdown = html_to_markdown(safe_html)",
         "    safe_html = clean_html(raw_html)\n"
         "    # 给 h2/h3/h4 补锚点 id —— 前台左侧目录靠它跳转\n"
         "    safe_html, toc = inject_heading_ids(safe_html)\n"
         "    markdown = html_to_markdown(safe_html)"),

        # ③ 日志带上目录标题数
        ("    logger.info('帮助中心文档已保存 docid=%s 管理员=%s html=%d字 md=%d字',\n"
         "                doc.docid, request.session.get('info', {}).get('uid'),\n"
         "                len(safe_html), len(markdown))",
         "    logger.info('帮助中心文档已保存 docid=%s 管理员=%s html=%d字 md=%d字 目录标题=%d个',\n"
         "                doc.docid, request.session.get('info', {}).get('uid'),\n"
         "                len(safe_html), len(markdown), len(toc))"),
    ]),

    ('project1/urls.py', [
        # ④ 导入前台视图
        ("from apps.helpdocs import admin_views as helpdocs_admin_views",
         "from apps.helpdocs import admin_views as helpdocs_admin_views\n"
         "from apps.helpdocs import views as helpdocs_views"),

        # ⑤ 两条前台路由
        ("    path('suadmin/helpdoc/image/delete/', helpdocs_admin_views.image_delete, name='helpdoc_admin_image_delete'),",
         "    path('suadmin/helpdoc/image/delete/', helpdocs_admin_views.image_delete, name='helpdoc_admin_image_delete'),\n"
         "       # 帮助中心（前台，默认不需要登录）\n"
         "    path('help/', helpdocs_views.doc_list, name='help_doc_list'),\n"
         "    path('help/<int:docid>/', helpdocs_views.doc_detail, name='help_doc_detail'),"),
    ]),
]

for path, pairs in TARGETS:
    s = io.open(path, encoding='utf-8', newline='').read()
    changed = 0
    for old, new in pairs:
        if new in s:                       # 这一处已经是目标状态了，跳过
            continue
        n = s.count(old)
        assert n == 1, '%s：锚点命中 %d 次（应为 1），先别继续：%r' % (path, n, old[:60])
        s = s.replace(old, new)
        changed += 1
    if changed:
        io.open(path, 'w', encoding='utf-8', newline='').write(s)
    print('  %-32s 实际改动 %d 处%s' % (path, changed, '' if changed else '（已经是目标状态）'))

print('完成')
