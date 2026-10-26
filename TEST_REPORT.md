# 测试报告

## 0.6.1 DeepSeek V4.1 Flash 视觉兼容增量（2026-10-26）

| 项 | 实际结果 |
|---|---|
| DeepSeek 模型别名规范化与官方 model_id | PASS |
| 视觉/OCR 探针安全格式容错与错误分类 | PASS |
| 后端全量 pytest | **91 passed, 3 warnings** |
| 前端 Vitest | **12 passed** |
| 前端生产构建 | PASS |

发布包已同步 `backend/app/ai.py`。线上发布仍需 WorkBuddy 完成新版本部署后，使用用户自己的 Key 重新检测一次视觉与中文读字能力。

## 0.6.0 书格拉底增量验证（2026-10-25 22:00，中国标准时间）

| 项 | 实际结果 |
|---|---|
| 后端全量 pytest | **89 passed, 3 warnings in 35.95s**（新增 `backend/tests/test_socratic.py` 21 项） |
| 前端 Vitest | **12 passed**（新增 `SocraticSession.test.tsx` 5 项） |
| 前端生产构建 | PASS（`tsc --noEmit` + Vite） |
| Edge E2E | **4 passed in 1.2m**（新增书格拉底模式切换/空状态/无 AI 安全降级用例） |

### 书格拉底后端测试覆盖（test_socratic.py，21 项全部 PASS）

| 分类 | 实际覆盖 | 结果 |
|---|---|---|
| 证据范围隔离 | 快照只含已读段落与最新笔记，未读章节不进快照、不进提示词 | PASS |
| 未读内容不泄露 | 完整 3 轮流程后检查全部模型提示词无未读章节文本 | PASS |
| 轮数边界 | rounds=2/6 → 422；3/5 → 201 | PASS |
| 幂等与冲突 | answer 相同文本重放返回 duplicate、不同文本 409；client_request_id 开局幂等、负载不一致 409；generate 成功后重试不重复调模型；finish 重复调用返回同一份报告 | PASS |
| 持久化 | 3 轮问答 + 报告全部落库可回看；作者原文/用户回答/AI 反馈分开存储 | PASS |
| 无 AI 安全降级 | 无已读证据 400 不建会话；BYOK 无验证连接 400 不建会话；模型超时 502 不落库不假装成功 | PASS |
| 推荐诚实性 | 只从书架真实书目选（book_id+书名双校验）；无其他书 → 空推荐+“需要补充书目来源”提示；编造 book_id → 502 | PASS |
| 引用校验 | 问题 focus 越界 502；反馈 citations 越界 502；报告回看位置非原文段落 502；kind 不按计划层次 502 | PASS |
| 云端免密钥回环 | start→generate(raw)→answer→generate(raw)→finish(拿提示词)→finish(raw) 全链路；非法 JSON 502 | PASS |
| 级联清理 | 删除整本书后 socratic_sessions/turns/reports 全清、详情 404、其余书籍不受影响 | PASS |
| 状态机防护 | 未生成问题就回答 409；已答轮次不可改写（409） | PASS |

### 前端组件测试（SocraticSession.test.tsx，5 项 PASS）

配置说明（证据边界文案、轮数 3—5）、开局→第一问→提交→反馈流转、提交失败保留输入、报告分块展示与“无推荐如实提示”、无书空状态禁用开始。

### Edge E2E（新增 1 项，累计 4 项 PASS）

书格拉底模式切换 UI 与证据边界文案、历史记录空状态、补建阅读会话后清空文字路由 → BYOK 明确降级（“请先在 AI 设置中配置并通过文字检测的连接”），且 `/api/socratic` 不产生半成品会话。截图 `artifacts/13-socratic-config.png`。

## 0.3.1 书籍管理增量验证（2026-10-25 13:27，中国标准时间）

| 项 | 实际结果 |
|---|---|
| 书名修改与搜索、原文版本保持不变 | PASS |
| 删除级联清理会话/已读范围/笔记/照片定位记录/本地照片 | PASS |
| 后端新增管理测试 | 2 passed |
| 后端全量 pytest | **65 passed, 3 warnings** |
| 前端 Vitest | **3 passed** |
| 前端生产构建 | PASS |

线上发布包已同步 `006_book_title_override.sql` 及对应前后端源码；WorkBuddy 输入框本轮未能接收任务，因此本增量由本地代码完成并通过上述自动化验证，待下一次发布动作完成后再做线上页面回归。

执行时间：2026-10-25 12:45—12:55（中国标准时间；本轮为云服务接入轮）
环境：Windows，Python 3.12（项目 `.venv`），Node 22，pnpm，Microsoft Edge 作为 Playwright channel。
标记规则：PASS = 实际运行并通过；FAIL = 实际运行失败；NOT RUN = 未执行或不在本轮范围。

## 1. 后端 pytest

命令：`pnpm test:backend`（等价 `node scripts/python.mjs -m pytest backend/tests -q`）

结果：**89 passed, 3 warnings in 35.95s** —— PASS（新增：书名修改、整本删除级联与本地文件清理、情境照片校验、云端情境照片、云端情境照片书删除回归、书格拉底 21 项）

覆盖摘要（在原有基础上新增）：

| 分类 | 实际覆盖 | 结果 |
|---|---|---|
| 证据接口 | `/api/evidence` 只返回已读证据、未读段落排除、text≤500、无需 AI 连接 | PASS |
| 云照片路径 | `photo_url` 签名 URL 回传、`cloud_path` 校验与持久化、不写本地文件、非法路径拒绝、无文件无 URL 400 | PASS |
| 公开 Origin 白名单 | 反代内部 Host + 白名单 Origin 通过、未列出 Origin 仍 403 | PASS |

## 2. 前端单元测试

命令：`pnpm test:frontend`

结果：**12 passed** —— PASS（书架检索/排序、导入顺序、摘要工具、章节分组与定位、分层选择只渲染当前章节选项、切章清空与回传、书格拉底配置/流转/失败保留输入/报告/空状态）

## 3. 前端生产构建

命令：`pnpm build`

结果：**PASS**；`tsc --noEmit` 通过，Vite 构建 4586 模块（含 `@tencent-ai/workbuddy-cloud-sdk`）。

## 4. Edge E2E

命令：`pnpm test:e2e`

结果：**4 passed in 1.2m** —— PASS（书架/版本/阅读情境、窄屏键盘 reduced-motion、真实设置表单与照片入口状态、书格拉底模式切换与无 AI 安全降级；段落选择已按新分层控件更新定位器）

## 5. WorkBuddy 云服务线上实测（本轮核心验证）

命令：`node scripts/cloud-verify.mjs A`（免登录探测）与 `node scripts/cloud-verify.mjs B`（真实 Edge 浏览器完整 UI，验证码经 Agent Mail 从参与者的注册邮箱读取（脚本不落盘邮箱地址）。）

目标：一次同源托管的试用发布（具体地址由环境变量 `YUEJI_BASE_URL` / `YUEJI_SHARECODE` 提供，不写入文档）

| 验证项 | 实测结果 | 标记 |
|---|---|---|
| 云 LLM 模型目录 | 返回 33 个模型（首个 id=auto） | PASS |
| 云 LLM 流式调用 | 真实流式返回答案，usage 含 prompt/completion/total tokens | PASS |
| 云 Auth 邮箱 OTP | 真实验证码登录云端身份成功（两轮，含账号创建与已有账号登录） | PASS |
| 云 Database 备份 | 「立即备份书房」写入 `backups` 并在列表读回 | PASS |
| 云 Storage 自检 | 上传探针→签名 URL 下载→内容比对→删除，页内显示全部正常 | PASS |
| 云端免密钥问答 | 真实流式回答基于已读证据（识别出“窗外没有山”），3 条引用全部通过证据校验 | PASS |
| 书名修改（书架 + 手账） | `scripts/book-mgmt-verify.mjs` 线上真实浏览器：导入→封面卡改名→手账改名，书脊与标题同步 | PASS |
| 整本删除 | 同上：手账内删除→确认→清理并回到书架，书脊消失 | PASS |
| 情境照片（文字+拍照） | 同上：保存会话附照片，时间线渲染 `<img>`（云端签名 URL），情境文字同时显示 | PASS |
| 截图证据 | `artifacts/07-cloud-service.png`、`artifacts/08-cloud-ask.png`、`artifacts/09-book-management.png` | PASS |

## 6. 安全与边界复核

- 跨站 Origin 仍被拒：线上 `Origin: https://evil.example` 登录返回 403；白名单 Origin 返回 200 —— PASS
- `frontend/src` 无 `localStorage/sessionStorage/apiKey` 匹配（SDK 会话由 SDK 自管理）—— PASS
- 后端 `api_key/secret_ref` 不回显、不写日志 —— PASS（回归）
- 云数据库 `backups` 表 RLS 四条 owner 策略由 MCP 复核在库 —— PASS

## 7. WorkBuddy 发布实测（累计）

- 发布链接可访问、带分享码 `/api/health` 正常 —— PASS
- 更新发布后测试账号仍在（单次实测；非正式 SLA）—— PASS
- 本轮两次更新发布后云服务与账号数据均正常 —— PASS

## 8. NOT RUN / 待用户或后续

| 项 | 状态 | 原因 |
|---|---|---|
| DeepSeek/OpenAI 真实在线供应商调用 | NOT RUN | 用户尚未在 AI 设置填真实 Key；云端免密钥通道已实测，但不替代 BYOK 验收 |
| 云备份一键还原界面 | NOT RUN | 当前支持下载 JSON 快照 |
| 真实照片 12 页标注集 OCR 命中率 | NOT RUN | 需真实视觉/OCR Key 与人工样本 |
| AI 知识卡片提炼/审核、思想图谱 | NOT RUN | 阶段 3/5 |

未运行项没有写成通过。

## 9. 手账加载与段落选择性能（0.5.0 实测）

测试书：900 段 / 30 章（`artifacts/perf-book.txt`，脚本生成），同一台机器、Edge 无头。

| 指标 | 旧版（线上实测） | 新版（线上实测） |
|---|---|---|
| 进入手账到段落选择可交互 | 1365 ms | **483 ms**（本地 351 ms） |
| 段落下拉渲染的 `<option>` 数量 | 1800（2 个可见下拉 × 900 段） | **122**（30 章节 + 当前章 31 段 + 当前章 31 段） |
| 展开下拉时的可用性 | 900 个长文本选项，出现指针迟滞/整机卡顿 | 每层 ≤ 31 项，操作正常 |
| 输入 30 字耗时（本地） | — | 309 ms |

加载提示：用 Playwright 延迟 `/api/books/{id}` 2.5 秒，实测 `.loading-ring` 与“正在翻动手账…”可见（截图 `artifacts/11-journal-loading.png`）；分层选择截图 `artifacts/12-passage-picker-live.png`。

验证脚本：`scripts/perf-measure.mjs`（本地）、`scripts/perf-before.mjs`（旧版线上）、`scripts/perf-after-live.mjs`（新版线上，含加载延迟与分层选择操作）。

## 图片识别可靠性与云端 AI 配置（0.6.2，2026-10-26）

命令：`pytest backend/tests -q`
结果：**101 passed, 3 warnings in 13.85s** —— PASS

新增 `backend/tests/test_vision_reliability.py`（10 项，在 `httpx.MockTransport` 层做契约验证）：

| 场景 | 期望行为 | 结果 |
|---|---|---|
| 429 之后成功 | 退避重试一次即成功 | PASS（共调用 2 次，尊重 Retry-After） |
| 5xx 持续失败 | 重试到上限后抛 server | PASS（共调用 3 次） |
| 400 参数错误 | 不重试，避免重复烧配额 | PASS（共调用 1 次） |
| 402 Insufficient balance | `payment_required`，提示余额不足 | PASS |
| `finish_reason=length` | 报 `response_truncated`，不再兜底误判 | PASS |
| 只返回 `reasoning_content` | 报 `reasoning_only` | PASS |
| 视觉请求体 | `image_url` 带 `detail=high`；视觉 ≥1000、OCR ≥4000 tokens | PASS |
| ` ```json ` 围栏答案 | 正确解析出 code / color | PASS |
| 4000×3000 PNG | 收敛为长边 ≤1568 px 的 JPEG，体积下降 | PASS |
| 非图片字节 | 原样返回，不吞异常 | PASS |

配套改动：视觉专用超时 90 秒（文本仍 30 秒）；新增类别在 `ai._error_status` 均有中文提示。

前端：`aiPrefs` 偏好 3 项单元用例，Vitest **15 passed**；生产构建 PASS。

## 演示稳定性小修（0.6.3，2026-10-26）

- 后端 **101 passed**、前端 Vitest **15 passed**、构建 PASS、线上健康检查 200。
- 修复：auth/db 连接未关闭（`with sqlite3` 只管事务）；每请求重复扫描迁移目录（加进程内缓存）；前端跨书/历史提问被当前书过滤掉；引用标签误触 HashRouter 跳回书架；401 判断改按状态码；照片路由的同步读保持在线程池（同步 FastAPI 路由下合法，此前的"阻塞"为误报并已回滚）。
- 三个并行审查代理共报告 38 条，本轮按"核心 demo 演示"范围只修上述演示路径相关项；其余（SSRF 加固、迁移原子性、幂等竞态、N+1、索引等）列入后续可选，未做。
