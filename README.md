# project1 · 技术内容社区 + FRP 隧道管理平台

一个自建的 Django 全栈站点，把三件事放在同一个系统里：

- **技术内容社区** —— 发帖、多级评论、点赞、积分体系
- **FRP 内网穿透服务管理** —— 用户自助申请与启停隧道、客户端分布式下载
- **基于中文语料的 RAG 问答** —— 关键词 + 向量混合检索，SSE 流式输出，答案可溯源

> 这不是一个教程项目。它跑在一台 4H4G 云服务器上，有真实用户、真实流量和真实故障要处理。
> 项目结构、日志规范与协作约定见 [AGENTS.md](AGENTS.md)。

---

## 目录

- [功能模块](#功能模块)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [项目结构](#项目结构)
- [本地运行](#本地运行)
- [配置说明](#配置说明)
- [生产部署](#生产部署)
- [工程实践](#工程实践)
- [已知限制与路线图](#已知限制与路线图)

---

## 功能模块

| 模块 | 能力 |
|---|---|
| **用户与认证** | 注册 / 登录 / 找回密码；bcrypt 密码哈希；Session 会话；JWT（HS256，3 天）供客户端调用 |
| **滑块验证码** | 自研拼图滑块；ticket 一次性消费；连续登录失败 2 次后强制触发 |
| **社区** | 发帖、多级评论（含子评论分页）、帖子/评论点赞、AJAX 无刷新交互 |
| **邮箱验证码** | Resend SMTP；每日额度、单邮箱 / 单 IP 双向频控；验证码与 ticket 双有效期 |
| **积分与兑换** | 积分余额、FRP 套餐兑换活动 |
| **FRP 隧道管理** | Web 端通过 frpc admin API 启停隧道、查看连接状态；角色权限隔离 |
| **客户端分发** | 安装包上传 / 下载；单文件上限 300MB；同 IP 每小时限次 |
| **RAG 问答** | zhparser 中文全文检索 + 页面标题实体链接 + 别名加权 + 可选向量混合检索（RRF 融合）；SSE 流式输出；引用可跳转溯源 |
| **LLM 对话** | Provider 配置入库，支持多模型切换与流式生成 |
| **帮助中心** | 帮助文档、故障树 FAQ |
| **后台权限** | RBAC，按权限码控制接口访问 |

---

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 框架 | Python 3.8 · Django 3.2 |
| 数据库 | PostgreSQL（`django.contrib.postgres`；RAG 依赖 `zhparser` 中文分词扩展） |
| 缓存 / 队列 | Redis（`django-redis`）：缓存、登录失败计数、限流、RAG 并发闸门 |
| 反向代理 / WSGI | Nginx + Gunicorn（systemd 托管） |
| 前端 | Django 模板 + 原生 JavaScript（无前端框架）；Markdown 渲染用 `marked` |
| 鉴权 | Session（主）+ JWT HS256（客户端接口） |
| 邮件 | Resend SMTP，或 `console` 模式（验证码打到日志，本地自测用） |
| 图形验证 | 自研滑块验证码（`apps/captcha`） |
| 设计规范 | `docs/THEME.md`（权威）+ `static/css/theme.css`（令牌唯一实现） |

---

## 系统架构

```
                     ┌──────────────┐
   Browser / Client ─┤    Nginx     │  TLS 终止 · 静态资源 · 反向代理
                     └──────┬───────┘
                            │ proxy_pass
                     ┌──────▼───────┐
                     │   Gunicorn   │  systemd: myproject
                     └──────┬───────┘
                            │ WSGI
                     ┌──────▼───────┐
                     │    Django    │
                     └──┬────┬───┬──┘
                        │    │   │
          ┌─────────────┘    │   └──────────────┐
   ┌──────▼──────┐   ┌───────▼──────┐   ┌───────▼────────┐
   │ PostgreSQL  │   │    Redis     │   │  LLM / Embedding│
   │ + zhparser  │   │ cache / 限流 │   │  (OpenAI 兼容)  │
   └─────────────┘   └──────────────┘   └────────────────┘
                            │
                     ┌──────▼───────┐
                     │  frpc admin  │  隧道启停 / 状态查询
                     └──────────────┘
```

**RAG 检索链路**（`apps/rag/services.py`）：

```
问题
 ├─ 别名展开（社区口语 → wiki 页面标题，JSON 可配）
 ├─ 实体链接（问题里直接出现的页面标题，长标题优先去重）
 ├─ zhparser 全文检索（先由 DB 分词拿 lexeme，再用 OR 拼 tsquery；
 │   不用 plainto_tsquery —— 中文自然问句几乎必然 0 命中）
 ├─ 字面覆盖率打分（绕开分词切错的场景：问题"几天成熟" vs 正文"成熟...天"）
 ├─ 章节名命中加权 + ts_rank
 └─（可选）向量通道 —— 用 RRF 与关键词结果融合
      ↓
   同页面限流 + 全局并发闸门 → 拼 Prompt → SSE 流式生成
```

---

## 项目结构

```
project1/
├── project1/               # Django 配置包（settings / urls / wsgi / asgi）
├── apps/                   # 12 个业务 app，全部平铺
│   ├── login/              # 用户、认证、社区帖子与评论
│   ├── frpServer/          # FRP 服务管理、frp 专用登录页
│   ├── rag/                # RAG 检索与流式问答
│   ├── llm_chat/           # LLM 对话
│   ├── llm_config/         # LLM Provider 配置表
│   ├── captcha/            # 滑块验证码
│   ├── mailservice/        # 邮件验证码与额度控制
│   ├── downloads/          # 客户端安装包分发
│   ├── pointsBalanceSystem/# 积分与兑换
│   ├── fault_tree/         # 故障树 FAQ
│   ├── helpdocs/           # 帮助文档
│   └── suadmin/            # 后台 RBAC 权限
├── templates/              # 全站级模板
├── static/                 # 全站静态资源（含 css/theme.css）
├── docs/                   # 设计规范等文档
├── scripts/                # 运维工具与一次性补丁归档
├── manage.py
└── AGENTS.md
```

---

## 本地运行

```bash
# 1. 依赖
python3.8 -m venv venv38
source venv38/bin/activate
pip install -r requirements.txt

# 2. 外部配置（settings.py 启动时强依赖这个文件，缺失会直接抛异常）
sudo mkdir -p /opt/config/django
sudo cp config.example.json /opt/config/django/project1settings.json
sudo chmod 600 /opt/config/django/project1settings.json
sudo chown $USER /opt/config/django/project1settings.json
# 然后编辑该文件填入真实值（见下一节）

# 3. 数据库
sudo -u postgres createdb project1
python manage.py migrate

# 4. 跑起来
python manage.py runserver 0.0.0.0:8000
```

> **注意**：配置文件路径在 `settings.py` 里是**硬编码绝对路径**（`/opt/config/django/project1settings.json`）。
> 本地开发也需要在这个位置放一份。这样做的好处是密钥永远不会被误提交进仓库。

---

## 配置说明

所有敏感项集中在仓库之外的一个 JSON 文件里，`settings.py` 读取后注入为 Django 配置。
仓库内只提供脱敏模板 `config.example.json`：

```json
{
  "secret_key": "CHANGE_ME",
  "debug": false,
  "allowed_hosts": ["example.com", "localhost", "127.0.0.1"],

  "database": {
    "name": "project1",
    "user": "project1",
    "password": "CHANGE_ME",
    "host": "127.0.0.1",
    "port": 5432
  },
  "redis": {
    "host": "127.0.0.1",
    "port": 6379,
    "db": 0,
    "password": "CHANGE_ME"
  },

  "token_secret_key": "CHANGE_ME",

  "openai_kimi": {
    "api_key": "CHANGE_ME",
    "base_url": "https://api.moonshot.cn/v1"
  },
  "rag_embedding": {
    "api_key": "CHANGE_ME",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "text-embedding-v4",
    "dim": 1024,
    "batch": 10
  },

  "frp": {
    "api_url": "http://127.0.0.1:7500",
    "admin_user": "admin",
    "admin_pwd": "CHANGE_ME",
    "public_host": "example.com",
    "server_addr": "example.com",
    "server_port": 7000,
    "config_token": "CHANGE_ME",
    "path": "/opt/frp/frp_0.65.0_linux_amd64"
  },

  "captcha": {},
  "mail": {
    "provider": "console",
    "resend_smtp_password": "CHANGE_ME",
    "resend_from_email": "noreply@example.com"
  }
}
```

`captcha` 与 `mail` 之外的字段缺失会导致启动失败；`captcha` 内各键都有默认值，可以留空对象。

---

## 生产部署

服务由 systemd 托管，Gunicorn 作为 WSGI 服务器，Nginx 反向代理并处理静态资源。

```ini
# /etc/systemd/system/myproject.service（示意）
[Unit]
Description=My Django Project
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=django
WorkingDirectory=/opt/projects/project1
ExecStart=/opt/projects/project1/venv38/bin/gunicorn project1.wsgi:application \
          --bind 127.0.0.1:8000 --workers 3 --access-logfile - --error-logfile -
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myproject
journalctl -u myproject -f          # 日志走 stdout，由 journald 采集
```

**日志策略**（有生产事故前科，务必遵守）：

- 应用日志写 `/opt/projects/project1/django.log`，`RotatingFileHandler`，10MB × 5 份备份
- 所有 logger 级别为 `INFO`（`django.db.backends` 为 `WARNING`）
- journald 通过 `/etc/systemd/journald.conf.d/99-size.conf` 限制 `SystemMaxUse=200M`

```bash
# 截断日志的正确方式（进程持有文件句柄，rm 不会释放空间）
: > /opt/projects/project1/django.log
```

---

## 工程实践

几个值得一看的实现细节：

1. **密钥全部外置**：仓库里没有任何密钥。写配置的脚本（`scripts/set_qwen_key.py`）从环境变量读值、原子写入、`chmod 600`、输出打码。
2. **中文全文检索不能用 `plainto_tsquery`**：它会要求所有词同时出现，中文自然问句几乎必然 0 命中。这里先用数据库自己的 zhparser 分词拿到 lexeme，再用 OR 拼 `tsquery`。
3. **分词会切错，所以补了一层字面覆盖率打分**：问题里的"几天成熟"和正文的"成熟…天"在词面上永远对不上，改用长词优先的字面覆盖来兜底。
4. **SSE 长连接要加并发闸门**：Gunicorn worker 数量有限，一条流式响应会占死一个 worker。`apps/rag/services.py` 里有基于 Redis 的全局并发计数与单用户限流。
5. **日志事故复盘**：模板变量查找失败以 DEBUG 级记录完整请求上下文，曾使单文件日志涨到 4.4GB 撑满磁盘。修复是三层的——handler 级别、轮转策略、journald 上限。

---

## 已知限制与路线图

**当前限制**

- 单机部署，无读写分离、无多实例
- RAG 的向量通道需要额外配置 embedding API；未配置时自动退回纯关键词检索
- `zhparser` 未安装时，Django 全文检索会降级到 `simple` 配置（能跑，召回质量下降）

**路线图**

- [ ] 补齐 `requirements.txt` 与依赖版本锁定
- [ ] `Dockerfile` + `docker-compose.yml`（Web / PostgreSQL / Redis 三服务）
- [ ] CI：`ruff` 静态检查 + `pytest` 单元测试 + 镜像构建
- [ ] Kubernetes manifests（Deployment / Service / Ingress / StatefulSet / ConfigMap / Secret）
- [ ] 把模板变量查找失败从源头消除（视图 GET 分支补 `error` 上下文）
