# AGENTS.md — project1 项目说明与协作约定

> 本文件写给**接手本项目的 AI 代理 / 新开发者**。
> 读完这一份，你应该能在 10 分钟内知道：这是什么项目、代码在哪、怎么跑、哪些东西不能碰、以及**怎么和项目负责人（陈晨）协作**。
>
> ⚠️ 本文件**不含任何密钥**。所有敏感配置都在服务器 `/opt/config/django/project1settings.json`，不在仓库里。

---

## 0. 一句话概括

一个从零自建的 **Django 全栈站点**，同时承载三件事：

1. **技术内容社区**（帖子 / 多级评论 / 点赞 / 积分）
2. **FRP 隧道服务的管理后台**（用户自助申请内网穿透、Web 端启停、客户端分发）
3. **基于中文 Wiki 语料的 RAG 问答**（zhparser 全文检索 + 可选向量混合检索 + 流式 LLM 输出）

---

## 1. 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 框架 | Python 3.8 · Django 3.2.25（**不要升级大版本**，模板与中间件按 3.2 写） |
| 数据库 | PostgreSQL（启用 `django.contrib.postgres`；RAG 用到 `zhparser` 中文分词扩展） |
| 缓存 / 队列 | Redis（`django-redis`），同时用作限流计数、并发闸门、失败次数锁 |
| 反向代理 / WSGI | Nginx + Gunicorn（systemd 托管，服务名 `myproject`） |
| 前端 | Django 模板 + 原生 JS（**无前端框架**）；Markdown 渲染用 CDN 的 `marked` |
| 鉴权 | Session（主）+ JWT HS256（客户端接口，有效期 3 天） |
| 邮件 | Resend SMTP，或 `console` 模式（验证码打到日志，本地自测用） |
| 图形验证 | 自研滑块验证码（`apps/captcha`），ticket 一次性消费 |
| 设计规范 | `docs/THEME.md`（权威）+ `static/css/theme.css`（令牌唯一实现） |

---

## 2. 目录结构

```
/opt/projects/project1/                 ← 仓库根（服务器工作目录）
├── project1/                           ← Django 项目配置包
│   ├── settings.py                     ← ★ 读外部 JSON 配置，不含密钥
│   ├── urls.py                         ← 全部路由注册在这一个文件
│   ├── wsgi.py / asgi.py
├── apps/                               ← 13 个业务 app（全部平铺，无嵌套）
│   ├── login/                          ← 用户、认证、社区帖子/评论
│   ├── frpServer/                      ← FRP 服务管理、frp 专用登录页
│   ├── rag/                            ← RAG 检索 + 流式问答（最复杂的一块）
│   ├── llm_chat/ llm_config/           ← LLM 对话与 Provider 配置表
│   ├── captcha/                        ← 滑块验证码（含背景图池 assets/captcha_bg）
│   ├── mailservice/                    ← 邮件验证码与额度控制
│   ├── downloads/                      ← 客户端安装包分发（限速 + IP 频控）
│   ├── pointsBalanceSystem/            ← 积分体系、FRP 兑换
│   ├── fault_tree/ helpdocs/           ← 故障树 FAQ、帮助文档
│   └── suadmin/                        ← 后台权限（RBAC，注意拼写是 su 不是 super）
├── templates/                          ← 全站级模板
├── static/                             ← 全站静态资源（含 css/theme.css）
├── docs/                               ← ★ 项目内文档（THEME.md、本文档）
├── scripts/                            ← ★ 运维工具与一次性补丁归档
│   ├── set_qwen_key.py                 ← 把 Qwen API Key 写入服务端配置（从环境变量读）
│   ├── gunicorn-memory-note.txt        ← 历史内存测量记录
│   └── one-off-patches/                ← 17 个历史一次性补丁脚本，仅存档，不参与运行
├── manage.py
├── requirements.txt
├── AGENTS.md                           ← 本文件
└── .gitignore
```

### 2.1 一个必须知道的路由细节

`settings.py` 里有 `sys.path.insert(0, BASE_DIR/"apps")`，但 `INSTALLED_APPS` 用的是
`apps.login.apps.LoginConfig` 这种全路径。**两种 import 风格并存**：

- 新代码统一用 `from apps.xxx.models import ...`
- 模板引用用 `{% url 'app:name' %}`，URL 的 `name` 在 `project1/urls.py` 集中注册

### 2.2 最容易走错的地方（血泪）

| 你以为 | 实际 |
|---|---|
| `/flogin/` 用 `login/login.html` | ❌ 用 **`frpServer/templates/frpServer/flogin.html`** |
| `/login/` 用 `frpServer/flogin.html` | ❌ 用 **`login/templates/login/login.html`** |

两个登录页长得几乎一样、错误提示写法也一样，**改之前先看 views 里的 `template = '...'` 变量**。
两个视图：`apps/login/views.py` → `user_login()`（通用）/ `frp_user_login()`（frp 专用）。

---

## 3. 运行环境

### 3.1 服务器

| 项 | 值 |
|---|---|
| 系统 | CentOS 7 |
| 项目路径 | `/opt/projects/project1` |
| 虚拟环境 | `/opt/projects/project1/venv38`（Python 3.8） |
| **运行方式** | **Docker Compose**（镜像 `sorielflow/soriel-web:2.0.0`，容器名 `soriel-web`） |
| 服务管理 | `docker compose up -d` / `down` / `restart web` / `logs -f web` |
| 进程模型 | 容器内 Gunicorn 3 worker，`--timeout 180`，绑定 `127.0.0.1:8000`（host 网络） |
| 日志 | **标准输出**：`docker compose logs -f web`（json-file 驱动，10MB × 3 上限） |
| 进程模型 | Gunicorn 多 worker（**注意：worker 数量少，长连接的 SSE 会占死 worker**） |
| 日志 | `/opt/projects/project1/django.log`（10MB × 5 轮转，上限约 60MB） |
| 媒体文件 | `/opt/projects/project1/media` |
| 客户端下载 | `/opt/projects/project1/downloads`（入库 `SorielConnection.exe`，单文件上限 300MB） |

### 3.2 配置文件（密钥唯一来源）

```
/opt/config/django/project1settings.json   权限 600，属主 django:django
```

`settings.py` 启动时**同步读取**这个文件，缺文件会直接抛异常起不来。里面包含：

`secret_key` · `debug` · `allowed_hosts` · `database{name,user,password,host,port}` ·
`redis{host,port,db,password}` · `token_secret_key` · `openai_kimi{api_key,base_url}` ·
`rag_embedding{api_key,base_url,model,dim}` · `frp{api_url,admin_user,admin_pwd,public_host,server_addr,server_port,config_token,path}` ·
`captcha{...}` · `mail{...}`

**修改方式**：不要 `vim` 手改这个文件。用 `scripts/set_qwen_key.py` 那种模式——
从环境变量读值、原子写入、chmod 600、输出打码。手改容易把 JSON 改坏导致整站起不来。

### 3.3 数据库与 Redis

- PostgreSQL：库名/用户/端口全部来自配置文件
- RAG 依赖 `zhparser` 扩展做中文全文检索；**没有装 zhparser 时检索会退回 `simple` 配置**（代码里有降级逻辑，不会崩，但召回质量会掉）
- Redis：同时承担缓存、登录失败计数、限流、RAG 并发闸门。**Redis 挂 = 登录锁失效 + 限流失效 + RAG 不可用**

### 3.4 部署与更新

**前提**：systemd 的 `myproject` 已停用（`systemctl stop/disable myproject`）。
Nginx 的 `proxy_pass` 指向 `127.0.0.1:8000`。

```bash
cd /opt/projects/project1
git pull origin main
docker compose up -d --build          # 改代码/依赖后必须 --build
docker compose exec web python manage.py migrate              # 有模型变更时
docker compose exec web python manage.py collectstatic --noinput   # 有静态变更时

---

## 4. 代码约定

### 4.1 日志（★ 有生产事故前科，务必遵守）

历史事故：`print`/DEBUG 级日志写满 **4.4GB** 单文件，把磁盘吃穿。已修复为轮转 + INFO。

**规则：**

1. **生产不写 DEBUG**。`project1/settings.py` 中 `handlers.file.level` 与所有 `loggers.*.level` 保持 `INFO`
2. **不要新增 `logging.FileHandler`**，统一复用已有的 `file` handler
3. 日志文件路径**必须是绝对路径**（相对路径会随工作目录漂移）
4. 异常日志用 `logger.exception(...)`；**不要** `logger.error(f"...{traceback.format_exc()}")`（会把整个栈塞进一行）
5. 高频路径（模板渲染、循环内、每个请求）**禁止**打日志
6. 新增 logger 一律 `'propagate': False`，避免重复写

### 4.2 密钥红线

- 任何密钥、token、密码**不得出现在仓库任何文件里**（含注释、示例、测试）
- 不得 `git add .`——只允许 `git add -u` 或明确点名的路径（历史上曾因此把 `.backup/` 提交上去）
- 新增配置项时：先加到 `project1settings.json`，再在 `settings.py` 里 `config.get(...)` 读取，**给默认值**

### 4.3 前端约定

- 设计令牌**只从** `static/css/theme.css` 取，禁止硬编码色值；规范见 `docs/THEME.md`
- 无构建步骤：不加 webpack/vite，直接写原生 JS
- 页面级样式写在模板 `<style>` 里可以，但**颜色仍须引用 CSS 变量**

### 4.4 数据库改动

- 用 `makemigrations` + `migrate`，**不要手改表结构**
- 涉及 RAG 的 `search_vector` 字段与触发器是手工 SQL 建的，改模型时要同步检查

---

## 5. 协作约定（★ 最重要的一节）

### 5.1 分工

| 角色 | 职责 |
|---|---|
| **项目负责人（陈晨）** | 拥有服务器与仓库写权限。**所有文件改动由他执行**，改动后 commit + `git push` 到 GitHub |
| **AI 代理** | 只读 GitHub 上的代码做分析与核对，**输出改法**，不假设自己能看到服务器实时状态 |

**代理获取代码的唯一可靠来源是有两个：**
1. GitHub 仓库 `git@github.com:neko4u/django.git`（分支 `main`）
2. 用户贴回来的终端输出

**代理不得基于记忆或推测描述服务器现状**，必须先用 API / raw 读取最新提交核对。

### 5.2 代理修改文件时的输出格式（强制）

每一次"要改某个文件"，必须给出**三段式**，缺一不可：

```
【文件绝对路径】
/opt/projects/project1/<相对仓库根的路径>

【锚点】Ctrl+F 搜索这一行原文（保证唯一）
<原文，逐字符精确，含缩进>

【替换为】
<新内容，逐字符精确，含缩进>
```

补充要求：
- 锚点**必须唯一**。如果原文在文件里出现多次，额外说明"第 N 处"或扩大锚点范围
- 一次给一个文件、一段改动；**不要把多个文件的改动混在一个代码块里**
- 改完给出**验证命令**（怎么确认生效，看哪一行输出）
- 涉及需要重启服务的，明确写出 `systemctl restart myproject`

### 5.3 代理确认改动时的流程

用户说"改完了"之后，代理应：
1. 通过 GitHub API 读取**最新 `main` 分支**上该文件的真实内容（不是本地缓存、不是上一轮的印象）
2. 逐项核对：改了什么、有没有漏、有没有顺带改坏别的地方
3. 用「✅ 已生效 / ❌ 未生效 / ⚠️ 部分生效」三态给结论，**每条附证据**

### 5.4 git 规范

- 分支：直接在 `main`（个人项目，不搞 PR 流程）
- 提交信息格式：

```
<type>(<范围>): <一句话说明>

- 具体改动点 1
- 具体改动点 2
```

`type` 用 `feat` / `fix` / `refactor` / `chore` / `docs`。
**禁止**提交信息只写"修复与优化""更新"这类无信息量的内容。

- 仓库地址：`github.com/neko4u/django`（旧名 `myprojec1` 已重命名，remote 已更新）

---

## 6. 已知问题 / 待办

| 优先级 | 问题 | 位置 |
|---|---|---|
| 高 | `console` handler 仍为 DEBUG，日志噪音转到 journald | `project1/settings.py` |
| 中 | `frpServer/flogin.html` 末尾有一段**完全重复**的 message-bar `<script>` 块 | 该文件底部 |
| 中 | `/flogin/`、`/login/` 的 GET 分支不传 `error`，模板 `{% if error %}` 每次都触发一次变量查找失败 | `apps/login/views.py` |
| 中 | `downloads/` 目录属主是 `root`，应用以 `django` 运行，上传可能无写权限 | 服务器权限 |
| 低 | `README.md`、`requirements.txt` 缺失 | 仓库根 |
| 低 | 无 `Dockerfile` / K8s manifests（规划中） | 仓库根 |

---

## 7. 常用命令速查

```bash
# 进入环境
cd /opt/projects/project1 && source venv38/bin/activate

# 服务
systemctl status myproject
systemctl restart myproject
journalctl -u myproject -n 100 --no-pager
journalctl --disk-usage                       # ★ 日志总占用

# 日志
ls -lh django.log*
tail -f django.log
: > django.log                                # 原地截断（★ 不要 rm，进程持有句柄）

# Django
python manage.py check
python manage.py makemigrations && python manage.py migrate
python manage.py collectstatic --noinput

# 配置（改完必须验证 JSON 合法）
python -c "import json;json.load(open('/opt/config/django/project1settings.json'));print('JSON OK')"

# 磁盘
df -h /opt
du -sh .git

# git
git status
git add -u            # ★ 不要用 git add .
git commit -m "..."
git push origin main
```

---

## 8. 变更记录

| 日期 | 内容 |
|---|---|
| 2026-11-03 | 建立本文件。同批完成：一次性补丁脚本归档、仓库根目录整理、日志轮转改造（4.4GB → 上限 60MB） |
| 2026-11-03 | 新增 `docs/THEME.md` 设计令牌规范 + `static/css/theme.css`；重构 RAG 问答界面（引用浮层、资料抽屉） |
