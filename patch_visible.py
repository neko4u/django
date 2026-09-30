# 帮助中心「前台可见 / 已隐藏」开关 —— 补丁脚本
#   ⚠️ 幂等：重复运行不会重复插入（会打印"已经是目标状态"）
#   在仓库根目录执行：  ./venv38/bin/python patch_visible.py
#
#   它改 4 个文件：
#     apps/helpdocs/models.py           加 is_visible 字段
#     apps/helpdocs/views.py            列表只列可见的 / 详情页隐藏的 404
#     apps/helpdocs/admin_views.py      doc_save 接收 is_visible
#     apps/helpdocs/templates/helpdocs/admin/doc_edit.html   顶栏加开关
import io

ED = 'apps/helpdocs/templates/helpdocs/admin/doc_edit.html'

TARGETS = [
    ('apps/helpdocs/models.py', [
        ("    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')\n"
         "    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')\n"
         "\n"
         "    class Meta:\n"
         "        db_table = 'helpcenter_doc'",
         "    # 前台是否可见。False = 下线：文档列表里不出现，直接输 /help/<docid>/ 也返回 404。\n"
         "    # 默认 True，所以已有文档和新建文档都不受影响。\n"
         "    is_visible = models.BooleanField(default=True, db_index=True, verbose_name='前台可见')\n"
         "\n"
         "    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')\n"
         "    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')\n"
         "\n"
         "    class Meta:\n"
         "        db_table = 'helpcenter_doc'"),
    ]),

    ('apps/helpdocs/views.py', [
        ('    """帮助中心首页：所有文档的列表。"""\n'
         "    docs = HelpCenterDoc.objects.all()          # Meta.ordering = ['-updated_at']",
         '    """帮助中心首页：只列前台可见的文档。"""\n'
         "    docs = HelpCenterDoc.objects.filter(is_visible=True)   # Meta.ordering = ['-updated_at']"),

        ("    doc = get_object_or_404(HelpCenterDoc, docid=docid)",
         "    # is_visible=False 的文档对前台等同于不存在 -> 直接 404\n"
         "    doc = get_object_or_404(HelpCenterDoc, docid=docid, is_visible=True)"),
    ]),

    ('apps/helpdocs/admin_views.py', [
        ("    doc.title = title\n"
         "    doc.content_html = safe_html\n"
         "    doc.content_md = markdown\n"
         "    doc.save()",
         "    # 「前台可见」开关：前端总是显式提交 '1' / '0'；\n"
         "    # 万一没带这个字段（例如浏览器缓存了旧页面），就保持原值不动，不擅自把文档下线。\n"
         "    raw_visible = request.POST.get('is_visible')\n"
         "    if raw_visible is not None:\n"
         "        doc.is_visible = raw_visible in ('1', 'true', 'True', 'on', 'yes')\n"
         "\n"
         "    doc.title = title\n"
         "    doc.content_html = safe_html\n"
         "    doc.content_md = markdown\n"
         "    doc.save()"),

        ("        'html_length': len(safe_html),\n"
         "        'md_length': len(markdown),\n"
         "    })",
         "        'html_length': len(safe_html),\n"
         "        'md_length': len(markdown),\n"
         "        'is_visible': doc.is_visible,\n"
         "    })"),
    ]),

    (ED, [
        # ① CSS
        ("        .hint { font-size: 12px; color: #b6c0cd; }",
         "        /* 前台可见开关 */\n"
         "        .vis {\n"
         "            display: flex; align-items: center; gap: 6px;\n"
         "            font-size: 13px; color: #5f6b7a; white-space: nowrap;\n"
         "            cursor: pointer; user-select: none;\n"
         "            padding: 5px 10px; border: 1px solid #e5e9f0; border-radius: 8px;\n"
         "            background: #fafbfd;\n"
         "        }\n"
         "        .vis:hover { border-color: #c8d4e3; }\n"
         "        .vis input { cursor: pointer; margin: 0; }\n"
         "        .vis.is-off { color: #c77700; border-color: #f0dfc0; background: #fffaf0; }\n"
         "\n"
         "        .hint { font-size: 12px; color: #b6c0cd; }"),

        # ② HTML
        ('    <span class="docid">docid: {{ doc.docid }}</span>',
         '    <span class="docid">docid: {{ doc.docid }}</span>\n'
         '    <label class="vis{% if not doc.is_visible %} is-off{% endif %}" id="vis-wrap" for="is-visible">\n'
         '        <input type="checkbox" id="is-visible"{% if doc.is_visible %} checked{% endif %}>\n'
         '        <span id="vis-label">{% if doc.is_visible %}前台可见{% else %}已隐藏{% endif %}</span>\n'
         '    </label>'),

        # ③ JS：取元素
        ("    var lenSaved = document.getElementById('len-saved');",
         "    var lenSaved = document.getElementById('len-saved');\n"
         "    var visWrap = document.getElementById('vis-wrap');\n"
         "    var visChk = document.getElementById('is-visible');\n"
         "    var visLabel = document.getElementById('vis-label');"),

        # ④ JS：绑定开关
        ("    editor.addEventListener('input', function () { refreshLen(); markDirty(); });\n"
         "    titleEl.addEventListener('input', markDirty);",
         "    editor.addEventListener('input', function () { refreshLen(); markDirty(); });\n"
         "    titleEl.addEventListener('input', markDirty);\n"
         "\n"
         "    // 「前台可见」开关：文案跟着勾选状态走，隐藏时整块变橙色\n"
         "    function refreshVis() {\n"
         "        var on = visChk.checked;\n"
         "        visLabel.textContent = on ? '前台可见' : '已隐藏';\n"
         "        visWrap.classList.toggle('is-off', !on);\n"
         "    }\n"
         "\n"
         "    visChk.addEventListener('change', function () { refreshVis(); markDirty(); });"),

        # ⑤ JS：提交时带上
        ("        fd.append('csrfmiddlewaretoken', csrfToken());",
         "        fd.append('csrfmiddlewaretoken', csrfToken());\n"
         "        fd.append('is_visible', visChk.checked ? '1' : '0');"),

        # ⑥ JS：保存成功文案区分
        ("            setStatus('已保存 ' + r.data.updated_at, 'ok');",
         "            setStatus('已保存 ' + r.data.updated_at\n"
         "                      + (r.data.is_visible ? '' : '（已隐藏，前台看不到）'), 'ok');"),

        # ⑦ JS：初始化
        ("    refreshLen();\n})();",
         "    refreshLen();\n    refreshVis();\n})();"),
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
    print('  %-58s 实际改动 %d 处%s' % (path, changed, '' if changed else '（已经是目标状态）'))

print('完成')
