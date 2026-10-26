// 对比测量：线上旧版（一次性铺开全部段落）在 900 段书上的表现。
import { chromium } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

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
page.on('dialog', (dialog) => void dialog.accept());
await page.goto(BASE + `/?sharecode=${CODE}`, { waitUntil: 'domcontentloaded' });
const authCard = page.locator('.auth-card');
if (await authCard.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)) {
  await page.getByLabel('用户名').fill('persistence-probe-20261025');
  await page.getByLabel('密码').fill('ProbePassword-2026');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText('persistence-probe-20261025', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}
const imported = await page.request.post(BASE + `/api/books/import?sharecode=${CODE}`, {
  multipart: { file: { name: 'perf-live.txt', mimeType: 'text/plain', buffer: fs.readFileSync(path.join(root, 'artifacts', 'perf-book.txt')) }, title: '性能对比书' },
});
const book = (await imported.json()).book;
const start = Date.now();
await page.goto(`${BASE}/?sharecode=${CODE}#book/${book.id}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.record-form select', { timeout: 120000 });
const interactive = Date.now() - start;
const options = await page.locator('.record-form option').count();
console.log('old_live_interactive_ms=', interactive, 'old_live_options=', options);
await page.getByRole('button', { name: '删除这本书' }).click();
await page.waitForSelector('.library-page', { timeout: 30000 });
console.log('cleanup=ok');
await browser.close();
