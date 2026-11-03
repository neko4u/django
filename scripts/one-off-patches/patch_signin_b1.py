# 签到活动模块 · 批① —— 数据模型
#   ⚠️ 幂等：重复运行不会重复插入（会打印"已经是目标状态"）
#   ⚠️ 先整体校验所有锚点，全部通过才写文件
#   在仓库根目录执行：  ./venv38/bin/python patch_signin_b1.py
#
#   改 1 个文件：
#     apps/pointsBalanceSystem/models.py
#       - PointRecord 增加 business_id 字段 + (user, scene, business_id) 唯一约束
#       - 新增 SignInActivity / SignInRecord 两个模型
import io
import os
import sys

MODELS = 'apps/pointsBalanceSystem/models.py'

# ---------------------------------------------------------------- 1) business_id
OLD_DETAIL = (
    "    detail_json = models.TextField(\n"
    "        blank=True, default='{}',\n"
    "        verbose_name='详细信息JSON',\n"
    "        help_text='可存储额外信息,如兑换的时长秒数,操作人IP,ID等'\n"
    "    )\n"
)
NEW_DETAIL = OLD_DETAIL + (
    "\n"
    "    # 业务ID：用来把「一次业务动作」和「一条积分流水」一一对应起来，做幂等兜底。\n"
    "    # 例如签到场景填的就是 SignInRecord.id。\n"
    "    # ⚠️ 必须 null=True + default=None：PostgreSQL 里 NULL 互不相等，\n"
    "    #    所以老流水和「不写 business_id 的场景」全都不受下面那条唯一约束影响；\n"
    "    #    如果写成 default=''，所有老行的 (uid, scene, '') 会互相撞车，加约束直接失败。\n"
    "    business_id = models.CharField(\n"
    "        max_length=64, null=True, blank=True, default=None,\n"
    "        verbose_name='业务ID',\n"
    "        help_text='同一次业务动作只允许写一条流水（配合唯一约束做幂等）',\n"
    "    )\n"
)

# ---------------------------------------------------------------- 2) 唯一约束
OLD_META = (
    "    class Meta:\n"
    "        indexes = [\n"
    "            models.Index(fields=['user', 'created_at']),\n"
    "            models.Index(fields=['scene', 'created_at']),\n"
    "            # models.Index(fields=['order_id']),\n"
    "        ]\n"
    "        verbose_name = '积分变动记录'\n"
    "        verbose_name_plural = verbose_name\n"
)
NEW_META = (
    "    class Meta:\n"
    "        indexes = [\n"
    "            models.Index(fields=['user', 'created_at']),\n"
    "            models.Index(fields=['scene', 'created_at']),\n"
    "            # models.Index(fields=['order_id']),\n"
    "        ]\n"
    "        constraints = [\n"
    "            # 兜底：同一用户 + 同一场景 + 同一业务ID 只允许一条流水。\n"
    "            # 这是「即使应用层判断出错，也不可能发两次积分」的最后一道防线。\n"
    "            # ⚠️ business_id 为 NULL 的行不受影响（PG 里 NULL 互不相等）。\n"
    "            models.UniqueConstraint(\n"
    "                fields=['user', 'scene', 'business_id'],\n"
    "                name='uniq_point_record_user_scene_business',\n"
    "            ),\n"
    "        ]\n"
    "        verbose_name = '积分变动记录'\n"
    "        verbose_name_plural = verbose_name\n"
)

# ---------------------------------------------------------------- 3) 两个新模型
NEW_MODELS = '''

# ---------------------------------------------------------------------------
# 签到活动
# ---------------------------------------------------------------------------

class SignInActivity(models.Model):
    """签到活动配置。

    可以配置多条并存；「现在能不能签」= 启用 + 在有效期内（两端都包含）。
    见 is_active_at()。

    设计要求（与 SignInRecord 的唯一约束配合）：
      - 同一活动、同一用户、同一签到日期只能签一次
      - 想表达「长期活动」就把 end_at 填一个很远的日期
    """

    name = models.CharField(max_length=128, verbose_name='活动名称')
    description = models.TextField(blank=True, default='', verbose_name='活动说明')

    enable = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')

    # ⚠️ 判定口径是 start_at <= now <= end_at（两端都包含）。
    #    想要「一直有效到当天结束」就把 end_at 填成那天的 23:59（面板里的默认值）。
    #    千万不要把 end_at 填成 00:00 —— 那等于当天还没开始就结束。
    start_at = models.DateTimeField(verbose_name='活动开始时间')
    end_at = models.DateTimeField(verbose_name='活动结束时间')

    points_per_sign_in = models.PositiveIntegerField(
        default=0, verbose_name='每次签到赠送积分')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['enable', 'start_at', 'end_at']),
        ]
        constraints = [
            # 起止时间填反了 = 活动永远不可能生效，这种错误让数据库直接拦住
            models.CheckConstraint(
                check=models.Q(end_at__gt=models.F('start_at')),
                name='signin_activity_time_order',
            ),
        ]
        verbose_name = '签到活动'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '%s（每次 %d 积分）' % (self.name, self.points_per_sign_in)

    def is_active_at(self, now):
        """这个活动在 now 时刻是否生效：启用 + 在有效期内（两端都包含）。"""
        return bool(self.enable and self.start_at <= now <= self.end_at)


class SignInRecord(models.Model):
    """签到记录。

    ★ uniq_signin_activity_user_date 是整套防重逻辑的地基：
      服务层用 INSERT ... ON CONFLICT (activity_id, uid, sign_date) DO NOTHING
      RETURNING id 直接试插，靠「有没有返回行」判断本次是不是真的首次签到，
      完全不依赖「先查再插」，也不依赖捕获异常。

    这里**不存**连续签到天数/奖励积分：
      - 连续天数随时可以从本表推算（同一用户按 sign_date 倒序），不需要提前固化；
      - 等真要做连续奖励时再加字段，避免现在建一堆用不上的列。
    """

    user = models.ForeignKey(
        'login.UserInfo',
        to_field='uid',
        on_delete=models.PROTECT,
        db_column='uid',
        related_name='sign_in_records',
        verbose_name='用户',
    )
    activity = models.ForeignKey(
        SignInActivity,
        on_delete=models.PROTECT,
        related_name='sign_in_records',
        verbose_name='签到活动',
    )

    # sign_date 是「按服务端固定时区算出来的那个自然日」，不是 sign_time 的日期截断；
    # 唯一约束用的就是它，所以它是防重的关键列。
    sign_date = models.DateField(verbose_name='签到日期')
    sign_time = models.DateTimeField(verbose_name='签到时间')

    points_awarded = models.PositiveIntegerField(default=0, verbose_name='本次获得积分')
    operator_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='签到IP')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        ordering = ['-sign_time']
        constraints = [
            # ★ 同一活动 + 同一用户 + 同一签到日期 只能有一条。
            #   服务层的 ON CONFLICT 就以它作为冲突目标。
            #   ⚠️ 必须是**普通**唯一约束：不能加 condition、不能 DEFERRABLE，
            #      否则 ON CONFLICT (activity_id, uid, sign_date) 会报
            #      "there is no unique or exclusion constraint matching the ON CONFLICT specification"。
            models.UniqueConstraint(
                fields=['activity', 'user', 'sign_date'],
                name='uniq_signin_activity_user_date',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'sign_date']),
            models.Index(fields=['activity', 'sign_date']),
        ]
        verbose_name = '签到记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return '%s %s +%d' % (self.user_id, self.sign_date, self.points_awarded)
'''

TARGETS = [
    (MODELS, [
        (OLD_DETAIL, NEW_DETAIL),
        (OLD_META, NEW_META),
        # 追加到文件末尾（用最后一行当锚点，保证只追加一次）
        ("        return f'{self.user_id} 兑换 {self.activity.name} "
         "({self.get_reward_type_display()} x{self.reward_value}) - {status}'",
         "        return f'{self.user_id} 兑换 {self.activity.name} "
         "({self.get_reward_type_display()} x{self.reward_value}) - {status}'" + NEW_MODELS),
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
                print('    锚点片段：%r' % old[:70])
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
