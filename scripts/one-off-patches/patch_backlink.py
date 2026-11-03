# helpdoc 新增「允许返回帮助中心」开关 —— 补丁脚本
#   ⚠️ 幂等：重复运行不会重复插入（会打印"已经是目标状态"）
#   ⚠️ 先整体校验所有锚点，全部通过才写文件（不会改一半报错）
#   在仓库根目录执行：  ./venv38/bin/python patch_backlink.py
#
#   改 4 个文件：
#     apps/helpdocs/models.py                                  加 allow_back_link 字段
#     apps/helpdocs/admin_views.py                             doc_save 接收该字段
#     apps/helpdocs/templates/helpdocs/admin/doc_edit.html      顶栏加开关
#     apps/helpdocs/templates/helpdocs/doc_detail.html          底部返回入口按开关显示
import io
import os
import sys

ED = 'apps/helpdocs/templates/helpdocs/admin/doc_edit.html'
DD = 'apps/helpdocs/templates/helpdocs/doc_detail.html'

TARGETS = [
    ('apps/helpdocs/models.py', [
        ("    content_md = models.TextField(blank=True, default='', verbose_name='正文Markdown')",
         "    content_md = models.TextField(blank=True, default='', verbose_name='正文Markdown')\n"
         "\n"
         "    # 是否在文档页底部显示「← 返回帮助中心」。\n"
         "    # False = 不显示（例如这篇是发给外部人看的，不想让他顺着返回入口跳到帮助中心看到别的文档）。\n"
         "    allow_back_link = models.BooleanField(default=True, verbose_name='允许返回帮助中心')"),
    ]),

    ('apps/helpdocs/admin_views.py', [
        ("    doc.title = title\n"
         "    doc.content_html = safe_html\n"
         "    doc.content_md = markdown\n"
         "    doc.save()",
         "    # 「底部返回入口」开关：同样「没带这个字段就保持原值」，防止旧缓存页面把它悄悄关掉。\n"
         "    raw_back = request.POST.get('allow_back_link')\n"
         "    if raw_back is not None:\n"
         "        doc.allow_back_link = raw_back in ('1', 'true', 'True', 'on', 'yes')\n"
         "\n"
         "    doc.title = title\n"
         "    doc.content_html = safe_html\n"
         "    doc.content_md = markdown\n"
         "    doc.save()"),
    ]),

    (ED, [
        # ① CSS
        ("        .hint { font-size: 12px; color: #b6c0cd; }",
         "        /* 「返回帮助中心」开关 */\n"
         "        .allow-back {\n"
         "            display: flex; align-items: center; gap: 6px;\n"
         "            font-size: 13px; color: #5f6b7a; white-space: nowrap;\n"
         "            cursor: pointer; user-select: none;\n"
         "            padding: 5px 10px; border: 1px solid #e5e9f0; border-radius: 8px;\n"
         "            background: #fafbfd;\n"
         "        }\n"
         "        .allow-back:hover { border-color: #c8d4e3; }\n"
         "        .allow-back input { cursor: pointer; margin: 0; }\n"
         "        .allow-back.is-off { color: #8a97a8; border-color: #e0e4ea; background: #f7f8fa; }\n"
         "\n"
         "        .hint { font-size: 12px; color: #b6c0cd; }"),

        # ② HTML（放在「保存」按钮左边）
        ('    <button type="button" id="save-btn">保存（Ctrl+S）</button>',
         '    <label class="allow-back{% if not doc.allow_back_link %} is-off{% endif %}" id="allow-back-wrap"\n'
         '           for="allow-back" title="关闭后，这篇文档页面底部不显示「← 返回帮助中心」">\n'
         '        <input type="checkbox" id="allow-back"{% if doc.allow_back_link %} checked{% endif %}>\n'
         '        <span id="allow-back-label">底部返回入口：{% if doc.allow_back_link %}开{% else %}关{% endif %}</span>\n'
         '    </label>\n'
         '    <button type="button" id="save-btn">保存（Ctrl+S）</button>'),

        # ③ JS：取元素
        ("    var lenSaved = document.getElementById('len-saved');",
         "    var lenSaved = document.getElementById('len-saved');\n"
         "    var backWrap = document.getElementById('allow-back-wrap');\n"
         "    var backChk = document.getElementById('allow-back');\n"
         "    var backLabel = document.getElementById('allow-back-label');"),

        # ④ JS：绑定
        ("    titleEl.addEventListener('input', markDirty);",
         "    titleEl.addEventListener('input', markDirty);\n"
         "\n"
         "    // 「底部返回入口」开关\n"
         "    function refreshBack() {\n"
         "        var on = backChk.checked;\n"
         "        backLabel.textContent = '底部返回入口：' + (on ? '开' : '关');\n"
         "        backWrap.classList.toggle('is-off', !on);\n"
         "    }\n"
         "\n"
         "    backChk.addEventListener('change', function () { refreshBack(); markDirty(); });"),

        # ⑤ JS：提交时带上
        ("        fd.append('csrfmiddlewaretoken', csrfToken());",
         "        fd.append('csrfmiddlewaretoken', csrfToken());\n"
         "        fd.append('allow_back_link', backChk.checked ? '1' : '0');"),
    ]),

    (DD, [
        ('        <div class="doc-foot"><a href="/help/">← 返回帮助中心</a></div>',
         '        {% if doc.allow_back_link %}\n'
         '        <div class="doc-foot"><a href="/help/">← 返回帮助中心</a></div>\n'
         '        {% endif %}'),
    ]),
]


def read(path):
    return io.open(path, encoding='utf-8', newline='').read()


def main():
    # ---------- 第 1 遍：只校验，不写 ----------
    plan = []
    for path, pairs in TARGETS:
        if not os.path.exists(path):
            print('  ✗ 缺少文件：%s' % path)
            if path == DD:
                print('    → doc_detail.html 属于「批⑤（前台详情页）」，如果服务器上还没有它，')
                print('      先把批⑤ 落地再跑本脚本。')
            return 1
        s = read(path)
        for old, new in pairs:
            if new in s:                     # 已经是目标状态
                continue
            n = s.count(old)
            if n != 1:
                print('  ✗ %s：锚点命中 %d 次（应为 1）' % (path, n))
                print('    锚点片段：%r' % old[:70])
                return 1
            plan.append((path, old, new))

    if not plan:
        print('  4 个文件都已经是目标状态，无需改动。')
        return 0

    # ---------- 第 2 遍：整体写入 ----------
    by_file = {}
    for path, old, new in plan:
        by_file.setdefault(path, []).append((old, new))
    for path, pairs in TARGETS:
        if path not in by_file:
            print('  %-58s 已经是目标状态' % path)
            continue
        s = read(path)
        for old, new in by_file[path]:
            s = s.replace(old, new)
        io.open(path, 'w', encoding='utf-8', newline='').write(s)
        print('  %-58s 实际改动 %d 处' % (path, len(by_file[path])))
    print('完成')
    return 0


sys.exit(main())
