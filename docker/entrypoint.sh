#!/usr/bin/env bash
# ============================================================
# ============================================================
set -euo pipefail

BIND="${GUNICORN_BIND:-0.0.0.0:8000}"
WORKERS="${GUNICORN_WORKERS:-3}"
TIMEOUT="${GUNICORN_TIMEOUT:-180}"
LOG_LEVEL="${GUNICORN_LOG_LEVEL:-info}"
CONFIG="${DJANGO_CONFIG_FILE:-/opt/config/django/project1settings.json}"

# 配置前置检查。
# settings.py 读到这个文件就抛异常，早失败 + 明确提示，
# 比在容器日志里刷一屏 traceback 好排查得多。
if [ ! -r "$CONFIG" ]; then
    echo "[entrypoint] FATAL: 配置文件不存在或不可读: $CONFIG" >&2
    echo "[entrypoint] 请确认已挂载配置目录，例如:" >&2
    echo "[entrypoint]   -v /opt/config/django:/opt/config/django:ro" >&2
    exit 1
fi

# JSON 合法性检查：手改配置最容易漏括号，这里提前拦住
python - "$CONFIG" <<'PY' || { echo "[entrypoint] FATAL: 配置文件 JSON 格式非法" >&2; exit 1; }
import json, sys
json.load(open(sys.argv[1], encoding="utf-8"))
PY

echo "[entrypoint] bind=$BIND workers=$WORKERS timeout=$TIMEOUT log_level=$LOG_LEVEL"
echo "[entrypoint] config=$CONFIG"

exec gunicorn project1.wsgi:application \
    --chdir /opt/projects/project1 \
    --workers "$WORKERS" \
    --timeout "$TIMEOUT" \
    --bind "$BIND" \
    --log-level "$LOG_LEVEL" \
    --access-logfile - \
    --error-logfile -
