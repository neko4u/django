# 两件收尾：① detail_json 存成 Python repr 的老问题（共 4 处）② 顶部面包屑受开关控制
#   ⚠️ 幂等：重复运行不会重复改动
#   ⚠️ 先整体校验所有锚点，全部通过才写文件
#   在仓库根目录执行：  ./venv38/bin/python patch_followup.py
#
#   改 3 个文件：
#     apps/pointsBalanceSystem/services.py          import json + 3 处 detail_json
#     apps/frpServer/services.py                    1 处 detail_json
#     apps/helpdocs/templates/helpdocs/doc_detail.html   顶部「帮助中心」面包屑加开关
import io
import os
import sys

PTS = 'apps/pointsBalanceSystem/services.py'
FRP = 'apps/frpServer/services.py'
DD = 'apps/helpdocs/templates/helpdocs/doc_detail.html'

TARGETS = [
    (PTS, [
        # ① 补 import
        ("import logging\n\nfrom django.db import (",
         "import json\nimport logging\n\nfrom django.db import ("),

        # ② 积分流水
        ("            detail_json={\n"
         "                'reward_seconds': self.total_seconds,\n"
         "                'quantity': self.quantity\n"
         "            }",
         "            detail_json=json.dumps({\n"
         "                'reward_seconds': self.total_seconds,\n"
         "                'quantity': self.quantity\n"
         "            }, ensure_ascii=False)"),

        # ③ 时长流水
        ("            detail_json={\n"
         "                'activity_id': self.activity.id,\n"
         "                'points_deducted': self.total_points\n"
         "            }",
         "            detail_json=json.dumps({\n"
         "                'activity_id': self.activity.id,\n"
         "                'points_deducted': self.total_points\n"
         "            }, ensure_ascii=False)"),

        # ④ 兑换记录
        ("            detail_json={\n"
         "                'quantity': self.quantity,\n"
         "                'point_version_before': old_point_version,\n"
         "                'time_version_before': old_time_version\n"
         "            }",
         "            detail_json=json.dumps({\n"
         "                'quantity': self.quantity,\n"
         "                'point_version_before': old_point_version,\n"
         "                'time_version_before': old_time_version\n"
         "            }, ensure_ascii=False)"),
    ]),

    (FRP, [
        # ⑤ 结算时的时长流水（json 这个模块文件顶部已经 import 过了）
        ("                detail_json={'end_reason': end_reason},",
         "                detail_json=json.dumps({'end_reason': end_reason}, ensure_ascii=False),"),
    ]),

    (DD, [
        # ⑥ 顶部面包屑也受 allow_back_link 控制
        ('    <a class="hd-home" href="/help/">帮助中心</a>\n'
         '    <span class="hd-sep">/</span>\n'
         '    <span class="hd-title">{{ doc.title|default:"未命名文档" }}</span>',
         '    {% if doc.allow_back_link %}\n'
         '    <a class="hd-home" href="/help/">帮助中心</a>\n'
         '    <span class="hd-sep">/</span>\n'
         '    {% endif %}\n'
         '    <span class="hd-title">{{ doc.title|default:"未命名文档" }}</span>'),
    ]),
]


def read(path):
    return io.open(path, encoding='utf-8', newline='').read()


def main():
    plan = []
    for path, pairs in TARGETS:
        if not os.path.exists(path):
            print('  ✗ 缺少文件：%s' % path)
            return 1
        s = read(path)
        for old, new in pairs:
            if new in s:
                continue
            n = s.count(old)
            if n != 1:
                print('  ✗ %s：锚点命中 %d 次（应为 1）' % (path, n))
                print('    锚点片段：%r' % old[:80])
                return 1
            plan.append((path, old, new))

    if not plan:
        print('  已经是目标状态，无需改动。')
        return 0

    by_file = {}
    for path, old, new in plan:
        by_file.setdefault(path, []).append((old, new))
    for path, pairs in TARGETS:
        if path not in by_file:
            print('  %-52s 已经是目标状态' % path)
            continue
        s = read(path)
        for old, new in by_file[path]:
            s = s.replace(old, new)
        io.open(path, 'w', encoding='utf-8', newline='').write(s)
        print('  %-52s 实际改动 %d 处' % (path, len(by_file[path])))
    print('完成')
    return 0


sys.exit(main())
