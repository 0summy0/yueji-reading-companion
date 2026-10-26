import { chromium } from '@playwright/test';

// 目标环境完全由环境变量提供，源码不内置任何具体地址：
//   YUEJI_BASE_URL   形如 http://127.0.0.1:8000
//   YUEJI_SHARECODE  试用分享码（本地自建服务可留空）
const BASE = process.env.YUEJI_BASE_URL || 'http://127.0.0.1:8000';
const CODE = process.env.YUEJI_SHARECODE || '';
const APP_URL = CODE ? `${BASE}/?sharecode=${CODE}` : BASE;



async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();

  // 1. 只读健康检查
  const health = await (await page.request.get(`${BASE}/api/health?sharecode=${CODE}`)).json();
  console.log('health_status=', health.status, 'auth_required=', health.auth_required);

  // 2. 登录既有测试账号
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('用户名').fill('persistence-probe-20261025');
  await page.getByLabel('密码').fill('ProbePassword-2026');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText('persistence-probe-20261025', { exact: true }).waitFor({ timeout: 20000 });

  // 3. 提问页 → 切换书格拉底
  await page.goto(`${BASE}/?sharecode=${CODE}#ask`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '向阅读伴侣提问' }).waitFor({ timeout: 20000 });
  await page.getByRole('tab', { name: /书格拉底/ }).click();
  await page.getByRole('heading', { level: 2, name: /书格拉底 · 苏格拉底式理解检查/ }).waitFor({ timeout: 15000 });
  const roundsValue = await page.getByLabel('追问轮数').inputValue();
  const boundaryText = await page.getByText(/不会泄露未读内容/).isVisible();
  const scopeText = await page.getByText(/当前已读范围/).isVisible();
  console.log('socratic_ui=', boundaryText && scopeText ? 'visible' : 'MISSING', 'default_rounds=', roundsValue);
  await page.screenshot({ path: 'artifacts/15-socratic-live-config.png', fullPage: true });

  // 4. 历史记录入口与空状态（该测试账号未建过书格拉底会话）
  await page.getByRole('button', { name: '看历史记录' }).click();
  const emptyHint = await page.getByText(/还没有书格拉底会话/).isVisible().catch(() => false);
  console.log('history_empty_state=', emptyHint);

  // 5. 无 AI 连接时开始 → 明确降级，不产生半成品会话
  const books = (await (await page.request.get(`${BASE}/api/books?sharecode=${CODE}`)).json()).items;
  console.log('book_count=', books.length);
  await page.getByRole('button', { name: /再开一局/ }).click();
  await page.getByRole('button', { name: /开始书格拉底/ }).click();
  const errorText = await page.locator('.socratic-config .form-error').textContent({ timeout: 15000 }).catch(() => '');
  console.log('degradation_message=', JSON.stringify(errorText.trim().slice(0, 80)));
  const sessions = (await (await page.request.get(`${BASE}/api/socratic?sharecode=${CODE}`)).json()).items;
  console.log('half_created_sessions=', sessions.length);

  // 6. 普通书童仍可用（模式切回后界面还原）
  await page.getByRole('tab', { name: /普通书童/ }).click();
  const tutorComposer = await page.getByLabel(/问题/).first().isVisible();
  console.log('tutor_still_ok=', tutorComposer);

  await browser.close();
}

main().catch((error) => {
  console.error('verify_failed=', error.message);
  process.exitCode = 1;
});
