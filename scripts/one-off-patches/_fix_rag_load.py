P = '/opt/projects/project1/apps/rag/management/commands/rag_load.py'
s = open(P, encoding='utf-8').read()

if "if opts['reset']:" in s:
    print('[SKIP] --reset 分支已存在')
else:
    old = """        with transaction.atomic():
            created_pages = 0"""
    new = """        with transaction.atomic():
            if opts['reset']:
                RagChunk.objects.all().delete()
                RagPage.objects.all().delete()
                self.stdout.write('[!] 已清空 rag_chunk / rag_page')

            created_pages = 0"""
    if old not in s:
        print('[FAIL] 找不到锚点，别手改，告诉我')
    else:
        open(P + '.bak', 'w', encoding='utf-8').write(s)
        open(P, 'w', encoding='utf-8').write(s.replace(old, new, 1))
        print('[OK] 已补回 --reset 分支（备份 %s.bak）' % P)

s = open(P, encoding='utf-8').read()
print('[CHECK] if opts["reset"] 存在:', "if opts['reset']:" in s)
