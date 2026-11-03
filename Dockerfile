# syntax=docker/dockerfile:1
# ==========================================================
# project1 · Django 全栈站点
# 多阶段构建：builder 只准备依赖轮子，runtime 只带运行所需
#
# ★ 设计原则：整个构建不依赖任何 APT / Debian 软件源。
#   依据：
#     1. 43 个依赖在 cp38 上都有预编译 wheel —— 不需要 build-essential
#     2. psycopg2-binary 自带 libpq 运行时 —— 不需要 libpq-dev
#     3. pytz 自带完整 TZif 时区库 —— 不需要 apt install tzdata
#
#   为什么这么做：国内访问 deb.debian.org 会长时间挂起；换阿里云镜像后
#   其 debian-security 池又存在同步滞后（索引已更新、.deb 还没同步，返回 404），
#   一次性要下 74.9MB / 478MB 磁盘。干脆一个包都不装。
#
#   与运行环境对齐要点：
#     - Python 3.8：与宿主机 venv38 一致
#     - 工作目录固定 /opt/projects/project1：settings.py 里
#       MEDIA_ROOT / DOWNLOAD['DIR'] / 日志路径都是写死的绝对路径
#     - gunicorn 参数对齐现有 systemd 单元，唯一改动是
#       unix socket -> TCP（容器的 socket 文件宿主机看不见）
# ==========================================================

# ---------- 阶段 1：下载依赖轮子（不编译） ----------
FROM python:3.8-slim-bullseye AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .

# 只下载 wheel，不做编译，因此不需要任何编译工具链。
# PyPI 官方源在国内较慢，改用阿里云镜像；若某个包在镜像里缺失，
# 删掉 --index-url 那行走官方源即可。
RUN pip wheel --wheel-dir /wheels -r requirements.txt \
        --index-url https://mirrors.aliyun.com/pypi/simple/ \
        --timeout 30 \
        --retries 3


# ---------- 阶段 2：运行时 ----------
FROM python:3.8-slim-bullseye AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=project1.settings \
    DJANGO_CONFIG_FILE=/opt/config/django/project1settings.json \
    TZ=Asia/Shanghai

# 非 root 运行。
# ⚠️ APP_UID / APP_GID 必须等于宿主机 django 用户的 uid/gid：
#      id -u django && id -g django
#    不一致会导致挂载 media/ downloads/ 后容器内没有写权限。
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app \
 && useradd -u ${APP_UID} -g app -m -s /bin/bash app

WORKDIR /opt/projects/project1

# ① 先装依赖 —— 放在代码之前，利用层缓存：
#    只改 Python 代码时这一层不失效，构建从几分钟降到几秒
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# ② 时区：pytz 已随上一步安装，它自带完整的 TZif 时区库。
#    已有系统 zoneinfo 就沿用，没有就软链到 pytz 的，省掉 apt install tzdata。
#    最后一行的 [tz] 输出用于在构建日志里直接确认时区生效。
RUN set -e; \
    if [ ! -e /usr/share/zoneinfo/Asia/Shanghai ]; then \
        PKG="$(python -c 'import pytz,os;print(os.path.dirname(pytz.__file__))')"; \
        rm -rf /usr/share/zoneinfo; \
        ln -sfn "$PKG/zoneinfo" /usr/share/zoneinfo; \
    fi; \
    ln -sfn /usr/share/zoneinfo/Asia/Shanghai /etc/localtime; \
    echo "Asia/Shanghai" > /etc/timezone; \
    python -c "import time;print('[tz]', time.strftime('%Y-%m-%d %H:%M:%S %Z'))"

# ③ 再拷代码 —— 变化最频繁的放最后一层
COPY --chown=app:app . .

# ④ 运行时目录。挂载卷会覆盖它们，但镜像自身也要能单独启动（便于 docker run 排查）
RUN mkdir -p /opt/projects/project1/media \
             /opt/projects/project1/downloads \
             /opt/projects/project1/staticfiles \
             /opt/projects/project1/logs \
             /opt/config/django \
 && chown -R app:app /opt/projects/project1 /opt/config

COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER app

EXPOSE 8000

# 用 Python 自检，避免为了 healthcheck 额外安装 curl。
# 注意 /flogin/ 返回 200 要求配置里 allowed_hosts 包含 127.0.0.1。
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/flogin/', timeout=4); sys.exit(0 if r.status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
