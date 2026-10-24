import os, shutil

BASE = '/opt/projects/project1'

def patch(rel, old, new, marker, label):
    p = os.path.join(BASE, rel)
    with open(p, encoding='utf-8') as f:
        s = f.read()
    if marker in s:
        print(f'[SKIP] {label}（已存在）')
        return
    if old not in s:
        print(f'[FAIL] {label} 找不到锚点，请手工改 {rel}')
        return
    shutil.copy(p, p + '.bak')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(s.replace(old, new, 1))
    print(f'[OK]   {label}')

patch('project1/settings.py',
      "    'django.contrib.staticfiles',\n    'apps.login.apps.LoginConfig',",
      "    'django.contrib.staticfiles',\n    'django.contrib.postgres',\n    'apps.login.apps.LoginConfig',",
      "'django.contrib.postgres'", "settings.py 加 django.contrib.postgres")

patch('project1/settings.py',
      "    'apps.suadmin',\n]",
      "    'apps.suadmin',\n    'apps.rag',\n]",
      "'apps.rag'", "settings.py 加 apps.rag")

patch('project1/urls.py',
      "    #llm_chat\n    path('chat/', include('apps.llm_chat.urls')),",
      "    #llm_chat\n    path('chat/', include('apps.llm_chat.urls')),\n    #wiki rag\n    path('wiki/', include('apps.rag.urls')),",
      "apps.rag.urls", "urls.py 加 /wiki/ 路由")

patch('templates/base.html',
      "<li><a href=\"{% url 'chat_page' %}\">LLM</a></li>",
      "<li><a href=\"{% url 'chat_page' %}\">LLM</a></li>\n                    <li><a href=\"{% url 'rag:wiki_page' %}\">wiki</a></li>",
      "rag:wiki_page", "base.html 加 wiki 导航")

print('\n--- 校验 ---')
for rel, needle in [('project1/settings.py', "'apps.rag'"),
                    ('project1/urls.py', "apps.rag.urls"),
                    ('templates/base.html', 'rag:wiki_page')]:
    s = open(os.path.join(BASE, rel), encoding='utf-8').read()
    print(('  OK  ' if needle in s else '  MISS ') + rel)
