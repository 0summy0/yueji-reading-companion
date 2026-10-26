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
const profileDir = path.join(root, 'artifacts', 'cloud-profile');
const browser = await chromium.launchPersistentContext(profileDir, { channel: 'msedge', headless: true });
const page = browser.pages()[0] || (await browser.newPage());
page.on('console', (msg) => { if (msg.type() === 'error') console.log('console_error=', msg.text().slice(0, 200)); });
page.on('pageerror', (err) => console.log('pageerror=', String(err).slice(0, 300)));
page.on('dialog', (dialog) => void dialog.accept());
await page.goto(BASE + `/?sharecode=${CODE}`, { waitUntil: 'domcontentloaded' });
const authCard = page.locator('.auth-card');
if (await authCard.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)) {
  await page.getByLabel('用户名').fill('persistence-probe-20261025');
  await page.getByLabel('密码').fill('ProbePassword-2026');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText('persistence-probe-20261025', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}
await page.getByRole('button', { name: '添加一本书' }).click();
await page.locator('#book-file').setInputFiles({ name: 'repro.txt', mimeType: 'text/plain', buffer: Buffer.from('# 第一章\n复现第一段。\n\n复现第二段。', 'utf-8') });
await page.locator('#import-book-title').fill('删除复现书');
await page.getByRole('button', { name: '导入并放上书架' }).click();
await page.getByRole('button', { name: /书脊：删除复现书/ }).waitFor({ timeout: 15000 });
const books = (await (await page.request.get(BASE + `/api/books?sharecode=${CODE}`)).json()).items;
const target = books.find((b) => b.title === '删除复现书');
await page.goto(`${BASE}/?sharecode=${CODE}#book/${target.id}`, { waitUntil: 'domcontentloaded' });
await page.getByRole('heading', { name: '删除复现书' }).waitFor({ timeout: 20000 });
// 保存一段带情境照片的会话（模拟真实使用顺序）
await page.getByRole('tab', { name: '今天读到这里' }).click();
const selects = page.locator('.record-form select');
await selects.nth(0).selectOption({ index: 0 });
await selects.nth(1).selectOption({ index: 1 });
await page.locator('.context-field textarea').fill('删除前的阅读情境');
await page.locator('.context-photo-field input[type="file"]').setInputFiles(path.join(root, 'artifacts', '07-cloud-service.png'));
await page.locator('.confirm-line input').first().check();
await page.getByRole('button', { name: '保存阅读会话' }).click();
await page.waitForSelector('.timeline-photos img', { timeout: 60000 }).catch(() => console.log('no_img_yet'));
await page.getByRole('button', { name: '删除这本书' }).click();
await page.waitForTimeout(6000);
console.log('hash=', await page.evaluate(() => window.location.hash));
console.log('has_library=', await page.locator('.library-page').isVisible().catch(() => false));
console.log('body=', (await page.locator('body').innerText().catch(() => '')).slice(0, 160).replace(/\n+/g, ' '));
await page.screenshot({ path: path.join(root, 'artifacts', 'debug-repro-delete.png'), fullPage: true });
await browser.close();
