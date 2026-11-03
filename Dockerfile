# syntax=docker/dockerfile:1
# ============================================================
# project1 · Django 全栈站点
# 多阶段构建：builder 只负责准备依赖，runtime 只带运行所需
#
# 与实际运行环境对齐要点：
#   - Python 3.8：与宿主机 venv38 一致，避免运行时分差异
#   - 工作目录固定 /opt/projects/project1：
#     settings.py 里 MEDIA_ROOT / DOWNLOAD['DIR'] / 日志路径
#     都是写死的绝对路径，路径必须一模一样
#   - gunicorn 参数对齐 /etc/systemd/system/myproject.service
#     唯一改动：unix socket -> TCP（容器的 socket 文件宿主机看不见）
# ============================================================

# ---------- 阶段 1：准备依赖轮子 ----------
FROM python:3.8-slim-bullseye AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# numpy / Pillow / psycopg2-binary / bcrypt / pydantic-core 在 cp38 上都有
# 预编译 wheel，正常情况下不走编译；这里保留工具链作为兜底，
# 避免某个包临时缺 wheel 时整个构建失败。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---------- 阶段 2：运行时 ----------
FROM python:3.8-slim-bullseye AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=project1.settings \
    DJANGO_CONFIG_FILE=/opt/config/django/project1settings.json \
    TZ=Asia/Shanghai

# 时区：容器默认 UTC，settings.py 里 TIME_ZONE=Asia/Shanghai 需要 tzdata
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && echo "Asia/Shanghai" > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

# 非 root 运行。
# ⚠️ APP_UID/APP_GID 必须等于宿主机 django 用户的 uid/gid，
#    否则挂载 media/ downloads/ 后容器没有写权限。
#    用 `id -u django && id -g django` 查，然后在 compose 里传参。
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app \
 && useradd -u ${APP_UID} -g app -m -s /bin/bash app

WORKDIR /opt/projects/project1

# ① 先装依赖 —— 放在代码之前，利用层缓存：
#    只改 Python 代码时，这一层不会失效，构建从几分钟降到几秒
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# ② 再拷代码 —— 变化最频繁的放最后一层
COPY --chown=app:app . .

# ③ 运行时目录。挂载卷会覆盖它们，但镜像自身也需要可启动（便于单独 docker run 排查）
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
