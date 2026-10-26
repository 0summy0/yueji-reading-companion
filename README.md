# 阅迹 · 持续性纸质书 AI 阅读伴侣

阅迹是本地优先的纸质书阅读手账。当前版本已经支持真实 BYOK 模型、照片定位候选确认、基于已读证据的提问和邀请制同学试用；没有 API Key 时，书房、导入、进度、原话、阅读情境和时间线仍然可用。

## 1. 功能状态

已实现：

- 实体书脊式 2.5D 书架、抽书封面卡、搜索排序、书脊样式编辑；书名可改、整本书可删除（二次确认后事务清理全部关联数据）。
- EPUB/UTF-8 TXT 安全导入、源文件去重、稳定段落 ID 与字符偏移。
- 手动阅读会话、UTC 时间、顺读/跳读/重读、可选阅读情境（文字 + 拍照双记录）和 `read_ranges`。
- 原话新增/修订、完整版本历史、证据链接、旧派生卡片 `stale`。
- 单书与全局时间线。
- OpenAI-compatible 真实 HTTP 适配器；默认提供 DeepSeek 官方预设（Base URL `https://api.deepseek.com`，模型 `deepseek-flash`，可编辑）。
- 后端 Fernet 加密保存用户 API Key；生产主密钥必须从环境注入，更新 Key 可留空保留旧 Key。
- 真实三项能力检测：极短文字任务、随机图片挑战、真实中文书页探针；分项显示文字/图片输入/中文读字状态。
- 照片上传前去 EXIF 和尺寸/体积校验；只发给用户选择的已验证路由；Top 3 候选确认前绝不推进度。
- “向阅读伴侣提问”：只检索当前用户的原话和已确认已读短原文，引用必须属于证据包；未读内容不进入模型上下文。
- “书格拉底”书童模式：一问一答式追问（3—5 轮，按“事实理解 → 因果与人物动机 → 你自己的判断”层次推进），开局固化已读证据快照，服务端校验每轮引用；结束后生成理解报告（理解清楚/模糊/你的观点/建议回看原文/下一步追问）与最多 3 本书架内真实书目推荐，无候选时明确提示不编造；BYOK 与云端免密钥两种引擎均遵守服务端证据约束。
- 邀请制注册登录、scrypt 密码哈希、HttpOnly + SameSite Cookie、每用户独立 SQLite 数据库、跨用户直接 ID 隔离。
- 全局 unsafe API Origin/CSRF 防护（支持 `YUEJI_PUBLIC_ORIGINS` 公开来源白名单，适配托管反代内部 Host）、登录/注册/提问/上传限流、生产安全启动校验。
- WorkBuddy 云服务四模块接入（`@tencent-ai/workbuddy-cloud-sdk`）：邮箱 OTP 云端身份、书房云备份（owner 级 RLS 隔离云数据库）、照片去 EXIF 直传云存储、提问页云端免密钥流式问答（引用必须在证据包内）。
- Dockerfile、docker-compose、非 root 运行、中文字体、healthcheck 和持久卷示例。

未实现或不冒充已实现：

- Anthropic/Gemini 原生适配器；只实现 OpenAI-compatible 请求格式。
- 自动判断照片位置；候选必须由用户确认。
- 知识卡片自动提炼/审核、跨书思想图谱、云备份一键还原（当前支持下载 JSON 快照）。
- 真实供应商在线验收：真实 DeepSeek BYOK 调用需用户在设置页填自己的 Key 后触发；云端免密钥问答通道已真实运行并实测通过。

## 2. 本地启动

### 安装

需要 Python 3.11+、Node.js 22+、pnpm 或 npm。

```bash
py -3 scripts/install.py        # Windows 常规环境
python3 scripts/install.py      # macOS/Linux
```

本机没有 npm 时，用 `WORK_ENVIRONMENT.md` 中的 bundled Python/pnpm 路径执行安装脚本，并设置 `PNPM` 环境变量。根目录脚本不依赖 npm 递归调用。

### 安全默认：邀请制登录

认证默认开启。启动前先创建邀请码：

```bash
pnpm auth:invite
```

然后启动：

```bash
pnpm dev
# 或 npm run dev；打开 http://127.0.0.1:5173
```

首次注册的同学会自动获得独立数据库和三本原创样书。原 `u_local` 本地数据不会自动交给任何访客；如需迁移到登录账号：

```bash
pnpm auth:create-user -- --username 旧主 --from-local
# 按提示输入至少 10 位密码
```

该迁移使用 SQLite backup API，会包含 WAL 中未检查点的数据，不会覆盖已有用户数据库。

### 纯本地开发模式

只在本机开发/自动化测试时可临时关闭认证：

```bash
YUEJI_AUTH_REQUIRED=false pnpm dev
```

生产环境（`YUEJI_ENV=production`）强制要求认证、Secure Cookie 和 `YUEJI_MASTER_KEY`，否则启动失败。

## 3. 在设置页接入 DeepSeek

1. 打开「AI 设置」。
2. 服务商预设选择 **DeepSeek 官方（推荐）**；默认：
   - Base URL：`https://api.deepseek.com`
   - 模型：`deepseek-flash`
3. 粘贴你自己的 DeepSeek API Key。Key 只发送到后端加密保存，不出现在 localStorage、日志或响应中。
4. 点击「连接并检测」。系统会真实执行三项小样本检测并产生少量 API 费用。
5. 在「按任务选择 Provider」里把：
   - 文字问答 → 已验证 DeepSeek 连接；
   - 拍照识别 → 通过视觉和中文读字的连接；
   - 独立 OCR → 可选另一条已验证 OCR 路线。
6. 回到书籍手账即可使用照片定位和证据式提问。

如果图片输入或中文读字未通过，文字问答仍可用；照片入口会明确要求手动定位。

## 4. 测试

```bash
pnpm test          # 后端 pytest + 前端 Vitest
pnpm build         # TypeScript + Vite 生产构建
pnpm test:e2e      # 自动启动前后端，用本机 Edge 无头运行
```

当前后端回归包含真实 HTTP 请求格式、图片 payload、SSRF、密文不回显、探针真值不泄露、错误分类、照片确认事务、证据引用校验、双用户隔离、邀请码并发、CSRF、生产启动校验等。

## 5. Docker 部署（有服务器时）

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export YUEJI_MASTER_KEY='粘贴生成的Fernet密钥'
docker compose up -d --build
```

创建邀请码：

```bash
docker compose exec yueji python -m app.auth_cli invite --label "同学试用"
```

数据持久化在 `yueji-data` 卷：`/app/data`。备份时停止容器后复制该卷内容；恢复时反向复制并重启。生产建议放在 HTTPS 反代之后，应用启用 `--proxy-headers`，并保持 `YUEJI_SECURE_COOKIES=true`。

## 6. 部署自己的试用环境

托管部署沿用同源形态：把本项目作为单端口 HTTP 服务发布，监听 `PORT`、绑定 `0.0.0.0`，并用环境变量注入运行参数：

- `YUEJI_PUBLIC_ORIGINS=https://<你的应用域名>`——不配会让反代内部 Host 与浏览器 Origin 不一致，带 Origin 的 POST 被判跨站拒绝；
- `YUEJI_ENV=trial`、`YUEJI_AUTH_REQUIRED=true`、`YUEJI_SECURE_COOKIES=true`；
- 首次使用先用 CLI 生成邀请码（`docker compose exec yueji python -m app.auth_cli invite --label "试用邀请"`），不要开放公开注册。

已实测：更新发布后原登录会话仍然有效，说明托管沙箱在一次更新中保留了 SQLite 与会话数据；但这不是平台正式持久卷承诺，重要数据仍应定期导出备份——应用内「云服务」页支持把书房打包备份到云端并下载 JSON 快照。

Cloud Service 已接入：邮箱 OTP 云端身份、书房云备份、照片直传云存储、免密钥云端问答四个模块均真实接线。云端所需要的三个前端公开值由部署方在构建时通过 `VITE_WB_ENDPOINT`、`VITE_WB_OAUTH_RELAY`、`VITE_WB_PUBLISHABLE_KEY` 注入（见 `.env.example`），源码不含任何具体环境地址。BYOK DeepSeek 与免密钥云端问答并存，互不替代。

## 7. 数据与安全契约

- 锚点基于电子版本段落和字符偏移，不使用纸书页数百分比。
- 只有用户确认顺读才扩连续范围；跳读/重读不填中间。
- 原话只增版本；编辑后旧派生卡片置 `stale`。
- 照片在候选确认前不推进度；禁止静默切换照片服务商。
- 问答先过滤当前用户与已读范围，再检索；模型引用不存在即拒绝展示。
- API Key 由后端 Fernet 加密保存；响应、日志和 422 错误不回显 Key。
- 自定义模型端点只允许管理员配置的主机清单，校验 HTTPS、443、DNS 公网地址，禁止重定向。

## 8. 目录速查

- `backend/app/providers/openai.py`：真实 OpenAI-compatible/DeepSeek HTTP 适配器。
- `backend/app/ai.py`：连接、三项探针、任务路由。
- `backend/app/photos.py`：照片安全处理、Top 3、确认事务（支持云存储签名 URL 回传）。
- `frontend/src/cloud/config.ts`：云服务 publicConfig 与单例 client。
- `frontend/src/cloud/cloudService.ts`：Auth/Database/Storage/LLM 四模块封装。
- `backend/app/asking.py`：已读证据过滤与真实问答。
- `backend/app/auth.py`、`auth_cli.py`：邀请制账号、会话、本地数据迁移。
- `backend/migrations/003*.sql`、`004*.sql`：照片确认关联和阅读情境等迁移。
- `frontend/src/components/Settings.tsx`：DeepSeek/BYOK 设置与三项检测。
- `frontend/src/components/Journal.tsx`：手账、阅读情境、照片候选确认。
- `frontend/src/components/AskPage.tsx`：证据式问答。
- `Dockerfile`、`docker-compose.yml`：通用部署方案。
