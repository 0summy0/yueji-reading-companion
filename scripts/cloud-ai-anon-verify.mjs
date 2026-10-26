// 线上验证：WorkBuddy 云端 AI 与云存储登录解耦（不登录云身份也能调用模型跑完书格拉底）。
import { chromium } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 目标环境完全由环境变量提供，源码不内置任何具体地址：
//   YUEJI_BASE_URL   形如 http://127.0.0.1:8000
//   YUEJI_SHARECODE  试用分享码（本地自建服务可留空）
const BASE = process.env.YUEJI_BASE_URL || 'http://127.0.0.1:8000';
const CODE = process.env.YUEJI_SHARECODE || '';
const APP_URL = CODE ? `${BASE}/?sharecode=${CODE}` : BASE;


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const USER = process.env.APP_USER || 'persistence-probe-20261025';
const PASS = process.env.APP_PASS || 'ProbePassword-2026';

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage();

// 0) 健康检查（只读）
const health = await page.request.get(`${BASE}/api/health?sharecode=${CODE}`);
console.log('health=', health.status());

await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });

// 1) 书房账号登录（阅迹自己的账号，不涉及云端邮箱验证码）
const authCard = page.locator('.auth-card');
if (await authCard.waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false)) {
  await page.getByLabel('用户名').fill(USER);
  await page.getByLabel('密码').fill(PASS);
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText(USER, { exact: true }).waitFor({ state: 'visible', timeout: 20000 });
}
console.log('app_login=ok');

// 2) 未登录云身份时，AI 与数据处理页仍能读到云端模型目录
await page.getByRole('button', { name: 'AI 与数据处理' }).click().catch(async () => {
  await page.getByRole('button', { name: /设置|AI/ }).first().click();
});
await page.locator('.cloud-ai-section').waitFor({ timeout: 20000 });
await page.locator('.cloud-ai-badge.ok').waitFor({ timeout: 30000 });
const badge = await page.locator('.cloud-ai-badge').textContent();
console.log('cloud_ai_badge=', badge);
const modelCount = await page.locator('.cloud-ai-grid select').nth(1).locator('option').count();
console.log('models_without_login=', modelCount);
await page.screenshot({ path: path.join(root, 'artifacts', '13-cloud-ai-config.png'), fullPage: true });

// 3) 默认回答方式设为云端 AI，并保留偏好
await page.locator('.cloud-ai-grid select').first().selectOption('cloud');
await page.waitForTimeout(400);
const stored = await page.evaluate(() => window.localStorage.getItem('yueji.cloud-ai.prefs.v1'));
console.log('prefs_persisted=', stored ? 'yes' : 'no');

// 4) 确认至少有一本书与一次阅读会话（制造已读证据）
await page.getByRole('button', { name: '书房', exact: true }).click();
await page.waitForSelector('.library-page', { timeout: 20000 });
const books = (await (await page.request.get(`${BASE}/api/books?sharecode=${CODE}`)).json()).items;
console.log('books=', books.length);
const book = books.find((item) => item.progress.passage_count > 0) || books[0];
if (!(await page.getByRole('button', { name: new RegExp(`书脊：${book.title}`) }).isVisible().catch(() => false))) {
  await page.getByRole('button', { name: '添加一本书' }).click();
  await page.locator('#book-file').setInputFiles(path.join(root, 'samples', '窗外有座小山.txt'));
  await page.locator('#import-book-title').fill('窗外有座小山');
  await page.getByRole('button', { name: '导入并放上书架' }).click();
}
// 没有已读会话就补一次顺读
let sessions = (await (await page.request.get(`${BASE}/api/books/${book.id}/sessions?sharecode=${CODE}`)).json()).items;
if (!sessions.length) {
  const passages = (await (await page.request.get(`${BASE}/api/books/${book.id}/passages?sharecode=${CODE}`)).json()).items;
  await page.request.post(`${BASE}/api/books/${book.id}/sessions?sharecode=${CODE}`, { data: {
    started_at: '2026-10-26T00:30:00+08:00', ended_at: '2026-10-26T00:50:00+08:00',
    timezone: 'Asia/Shanghai', start_anchor: passages[0].id, current_anchor: passages[Math.min(2, passages.length - 1)].id,
    session_type: 'sequential', sequential_confirmed: true, anchor_read_confirmed: true,
    client_request_id: `anon-cloud-${Date.now()}`,
  }});
  sessions = (await (await page.request.get(`${BASE}/api/books/${book.id}/sessions?sharecode=${CODE}`)).json()).items;
}
console.log('read_sessions=', sessions.length);

// 5) 提问页 → 书格拉底 → 云端 AI（全程未登录云存储身份）→ 跑完 3 轮并出报告
await page.getByRole('button', { name: '提问' }).click();
await page.getByRole('tab', { name: /书格拉底/ }).click();
await page.locator('.socratic-config select').nth(1).selectOption('3');
await page.locator('.socratic-config select').nth(2).selectOption('cloud');
await page.getByRole('button', { name: /开始书格拉底/ }).click();

const answers = [
  '他注意到窗外的小山后，先是没有立刻说出口，而是把它当成一个可以反复确认的东西。',
  '我觉得是因为最近的变动让他需要一个不动的参照物，小山在空间上没变，所以他才反复确认。',
  '我不同意“这只是普通的走神”；我读到的是他主动想确认，而不是被动的注意力转移。',
];
let reportVisible = false;
for (let round = 0; round < 3; round += 1) {
  const question = await page.locator('.socratic-question-text').first().textContent({ timeout: 120000 }).catch(() => null);
  if (!question) break;
  console.log(`round_${round + 1}_question=`, question.slice(0, 50));
  await page.locator('.socratic-current textarea').fill(answers[round]);
  await page.getByRole('button', { name: '提交回答' }).click();
  await page.waitForTimeout(1500);
  reportVisible = await page.locator('.socratic-report').waitFor({ timeout: 180000 }).then(() => true).catch(() => false);
  if (reportVisible) break;
  await page.locator('.socratic-waiting').waitFor({ timeout: 10000 }).catch(() => {});
  const retry = page.getByRole('button', { name: '继续生成' });
  if (await retry.isVisible().catch(() => false)) await retry.click();
  await page.locator('.socratic-question-text').first().waitFor({ timeout: 120000 }).catch(() => {});
}
console.log('report_generated_without_cloud_login=', reportVisible);

if (reportVisible) {
  await page.screenshot({ path: path.join(root, 'artifacts', '14-socratic-cloud-anon.png'), fullPage: true });
  const recCount = await page.locator('.socratic-recommendation').count();
  const noteText = await page.locator('.socratic-no-recommendation').textContent().catch(() => null);
  console.log('recommendations=', recCount, 'fallback_note=', noteText ? noteText.trim().slice(0, 40) : 'none');
}

await browser.close();
if (!reportVisible) process.exit(1);
