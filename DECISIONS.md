# 设计决策

## D01 · 本地 SQLite 是事实源，AI 不是

书架、原文索引、会话、范围、原话与版本先在一个本地事务中保存。Mock/真实服务是否可用不影响这些写入。后续卡片与回答只能是可重建派生物。

## D02 · 锚点绑定电子版本，不绑定纸书页码百分比

`passages` 同时保存 `edition_id + chapter_order + passage_order + position + start_char/end_char + hash`。字符偏移基于按阅读顺序拼接的提取文本，段落间使用两个换行符。`work` 与 `edition` 分表，避免错版内容沿用旧锚点。

## D03 · 当前位置、最远范围与实际已读范围分开

会话保存当前位置；`read_ranges` 只保存用户确认的事实。顺读勾选才写入起止连续范围；跳读/重读默认只写结束锚点。范围合并仅发生在重叠或相邻时，不用跳读把中间填满。

## D04 · 原话只增版本，不覆写

`notes` 是身份，`note_versions` 保存每次原文。编辑后新增证据链接，并将所有引用旧版本的未撤销卡片标记 `stale`。阶段 3 的重提炼仅写入持久化任务占位，不在本轮伪装执行。

## D05 · 时间与幂等必须先规范化

带时区时间统一转 UTC ISO 字符串后入库，时区单列保留。`client_request_id` 搭配书籍/有效负载 SHA-256；完全相同的重试返回已有实体，不同书籍或内容复用 ID 返回 409。

## D06 · EPUB 不落地解包，不渲染原始 HTML

解析器只在内存读取 ZIP 必要成员，按 spine 提取纯文本。限制上传、展开、单成员、条目和压缩比；拒绝穿越、加密、异常 MIME、脚本/嵌入/事件属性。XML 使用 defusedxml。这样既避免路径写入，也避免把书内指令或脚本当成应用内容执行。

## D07 · Mock 是明确标注的离线场景演员

Provider 抽象包含 `generate_text / analyze_image / extract_structured / embed_text`，OCR 单独定义 `ocr_page`。Mock 用内存合成 PNG 与私有真值模拟分项校验，真值不进入提示词。所有 UI 和 API 均带「模拟检测，不代表真实API能力」。

Mock 不收集 Key；后端拒绝真实 Provider，直至阶段 2 完成凭据安全存储与真实适配器。配置指纹变化会把旧检测置为 `stale`，随后自动重新检测。

## D08 · 任务路由采用完整替换语义

`PUT /api/ai/task-routes` 先验证所有非空路由，再在事务中删除旧路由并写入新集合。因此空对象和「不配置」能可靠清空，且不会在校验失败时损失旧配置。

## D09 · CSS 2.5D 书脊优先于重型 3D

每本书由独立按钮生成书脊，包含材质、排版、宽高与封面卡，不把封面图片压窄。桌面使用轻量 transforms；触屏和 `prefers-reduced-motion` 下取消 3D，移动端书架横向滚动，完整可访问名称与搜索补足窄书脊。

## D10 · 无 npm 也可复现运行

安装脚本支持 pnpm/npm/corepack 与 `PNPM` 环境变量。根目录 build/test 脚本直接调用项目内 TypeScript、Vite、Vitest 和 Python，不使用 npm 递归。E2E 用本机 Edge，不依赖浏览器下载。

## D11 · 阅读情境是可选的原始记录

阅读会话增加 `reading_context`（002 迁移，最大 1000 字）。它由用户手动填写并参与幂等有效负载；留空可保存，不做打卡压力。该文字属于 L0 原始证据，不接入定位权限、天气 API 或模型推测，时间线原样回看。

## D12 · 真实 Provider 是后端独立 HTTP 网关

首个真实适配器采用 OpenAI-compatible Chat Completions，并内置可编辑 DeepSeek 官方预设。请求由后端用 httpx 发起，禁重定向，流式限制响应总字节；`response_format` 不被支持时只退化重试一次。模型名、HTTP 200 或供应商品牌都不算能力证明。

## D13 · BYOK 凭据与真实调用必须过安全闸门

真实连接保存前校验 HTTPS、443、管理员允许域名、DNS 公网地址，并拒绝 URL 用户信息/查询/片段。API Key 用 Fernet 加密，主密钥独立于数据库；生产缺失主密钥/认证/Secure Cookie 时启动失败。更新连接留空 Key 表示保留旧 Key，任何响应、日志和校验错误不回显凭据。

## D14 · 能力探针按“连接 + 模型 + 端点 + 凭据版本”验证

保存或修改真实连接后，后端实际发送三类小样本：文字任务、随机图片挑战和真实中文书页探针。正确答案只在服务端内存，不进入提示词或元数据。text、vision_input、page_ocr 分项记录，401/429/超时/5xx 不得误判成“不支持图片”。

## D15 · 照片定位是候选确认，不是自动进度

照片先本地去 EXIF、限制尺寸和体积，只发送给用户显式选择且验证通过的 analyze/OCR 路由；不在服务商之间静默回退。OCR 结果只用于生成 Top 3 候选，确认前不写进度；确认与会话、照片、定位尝试在同一事务内完成，可安全重试。

## D16 · 问答先过滤证据，再让模型临时合成

`/api/ask` 只收集当前用户、当前选择范围内、最新原话版本和 `read_ranges` 覆盖的短原文。证据包带稳定 ID 发给文字模型；Pydantic 校验回答结构，引用必须属于证据包，否则整段回答拒绝展示。问答不自动写入用户长期观点。

## D17 · 同学试用采用“每用户一库”的硬隔离

认证库保存账号、邀请码和会话；每个登录用户拥有独立 SQLite 文件，原 `u_local` 数据库不会被第一个访客继承。直接 ID 接口天然无法跨库访问，同文件导入在不同用户下归属不同数据库。邀请码消费、用户名创建和计数使用 `BEGIN IMMEDIATE` 与条件 UPDATE，失败不扣次数。

## D18 · CSRF 与本地代理 Origin

所有 unsafe API 统一校验 Origin scheme/host/port。生产不信任自定义转发头；本地 Vite 代理显式传递原始 Host，允许 localhost/127.0.0.1 同 scheme 的开发别名，避免把代理端口差误判为跨站。

## D19 · WorkBuddy 托管分“可运行”和“持久化已证实”

WorkBuddy Sites 可承载单端口 FastAPI，不等于已承诺本地 SQLite/照片/主密钥持久卷。Cloud Service 明确持久化数据、用户和文件，但要求 SDK/Origin 绑定。交付时必须把“能运行”和“数据已持久化”分开记录，未实测不得宣传。

## D20 · 云服务与书房账号并行，能力按模块真实接线

WorkBuddy 云服务复用同一 applicationId 开通（环境与应用一一对应），前端经 `@tencent-ai/workbuddy-cloud-sdk@dev` 初始化，publicConfig 三个公开值内嵌于 `frontend/src/cloud/config.ts`。云端身份（邮箱 OTP）与书房邀请账号是两套并行身份：前者只保护云资源（RLS/存储路径），后者继续保护阅读数据，UI 明确标注互不替代。四模块各自落在真实功能上：Auth=登录云端身份、Database=书房云备份、Storage=照片直传、LLM=免密钥问答；LLM 引用校验在客户端重做一遍（引用必须是 `/api/evidence` 证据包内 ID）。

## D21 · 托管反代下以公开来源白名单替代 Host 同源判断

托管平台把内部沙箱地址放进 Host 头，浏览器 Origin 与 Host 永不相等，导致所有带 Origin 的 POST 被判跨站。改为 `YUEJI_PUBLIC_ORIGINS` 精确白名单（等价 CORS allowlist）：Origin 在白名单内即视为同源；未列出的 Origin 仍拒绝。本地开发保留 Host 同源与 Vite 原始 Host 透传路径。

## D22 · 照片优先云端持久化，服务端不再写本地照片文件

登录云端身份后，照片在浏览器去 EXIF（canvas 重绘）直传云存储，签名 URL 送后端识别；`photos.cloud_path` 记录云端对象路径（005 迁移），服务端不落盘照片文件。未登录云端时保持原本地兜底流程。两条路径都仍走“候选确认前不推进度”。
