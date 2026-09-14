"""FRP 巡检命令（建议 crontab 每分钟执行一次）

串起 services.py 里 4 个巡检任务：
  ① settle_expired_sessions      余额耗尽/到期 -> 自动结算断开
  ② settle_timeout_sessions      心跳超时(掉线) -> 按最后心跳结算
  ③ reconcile_rogue_connections  对账防伪(frps在线/redis无) -> 断连 + 递增拉黑
  ④ release_expired_bans         黑名单到期 -> 自动解除

用法:
    python manage.py patrol_frp                 # 手动跑一轮
    python manage.py patrol_frp --quiet         # cron 用: 无任何变更时不输出
    python manage.py patrol_frp --no-lock       # 调试: 跳过防重入锁

crontab(每分钟):
    * * * * * cd /opt/projects/project1 && ./venv38/bin/python manage.py patrol_frp --quiet >> /var/log/patrol_frp.log 2>&1
"""
import time
import uuid
import traceback

from django.core.cache import cache
from django.core.management.base import BaseCommand

from apps.frpServer import services as frp_services

LOCK_KEY = 'frp:patrol_lock'   # 防重入锁：上一轮没跑完，本轮跳过
LOCK_TTL = 100                 # 秒（>1轮耗时即可，异常卡死也能自动解锁）


class Command(BaseCommand):
    help = 'FRP 巡检：到期结算 / 心跳超时掉线 / 对账防伪 / 拉黑到期解除'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true',
                            help='本轮无任何变更时不输出（适合 cron）')
        parser.add_argument('--no-lock', action='store_true', dest='no_lock',
                            help='跳过防重入锁（调试用）')

    def handle(self, *args, **options):
        quiet = options['quiet']
        r = cache.client.get_client()
        token = str(uuid.uuid4())

        # --- 防重入：上一轮若还卡着（如 frps 无响应），本轮直接跳过 ---
        if not options['no_lock']:
            try:
                got = r.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL)
            except Exception as e:
                self.stderr.write(f'[patrol_frp] Redis 不可用: {e}')
                raise SystemExit(1)
            if not got:
                if not quiet:
                    self.stdout.write('上一轮巡检尚未结束，跳过本轮')
                return

        started = time.time()
        result = {}

        try:
            # 处理顺序
            tasks = (
                ('expired', '到期结算', frp_services.settle_expired_sessions),
                ('timeout', '心跳超时结算', frp_services.settle_timeout_sessions),
                ('orphan', '孤儿会话清理', frp_services.cleanup_orphan_sessions),
                ('rogue', '对账防伪', frp_services.reconcile_rogue_connections),
                ('unban', '黑名单到期解除', frp_services.release_expired_bans),
            )

            for key, label, fn in tasks:
                try:
                    result[key] = fn()
                except Exception as e:
                    result[key] = f'ERROR({e})'
                    self.stderr.write(f'[patrol_frp] {label} 异常: {e}')
                    self.stderr.write(traceback.format_exc())
        finally:
            # 只删自己加的锁（避免误删别人超时后新加的锁）
            try:
                cur = r.get(LOCK_KEY)
                if cur is not None:
                    cur = cur.decode() if isinstance(cur, bytes) else cur
                    if cur == token:
                        r.delete(LOCK_KEY)
            except Exception:
                pass

        changed = sum(v for v in result.values() if isinstance(v, int))
        if quiet and changed == 0:
            return

        cost = int((time.time() - started) * 1000)
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        self.stdout.write(
            f'[{stamp}] 巡检完成 {cost}ms | '
            f'到期结算 {result.get("expired")} | '
            f'超时结算 {result.get("timeout")} | '
            f'对账处理 {result.get("rogue")} | '
            f'解封 {result.get("unban")}'
        )
