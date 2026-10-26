// 聚焦诊断：情境照片保存后的服务端数据与前端渲染。
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
page.on('dialog', (dialog) => void dialog.accept());
page.on('response', (res) => { if (res.url().includes('/.cloud/storage')) console.log('storage_status=', res.status()); });
await page.goto(BASE + `/?sharecode=${CODE}`, { waitUntil: 'domcontentloaded' });
const authCard = page.locator('.auth-card');
if (await authCard.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)) {
  await page.getByLabel('用户名').fill('persistence-probe-20261025');
  await page.getByLabel('密码').fill('ProbePassword-2026');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText('persistence-probe-20261025', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}
await page.getByRole('button', { name: '添加一本书' }).click();
await page.locator('#book-file').setInputFiles({ name: 'img-check.txt', mimeType: 'text/plain', buffer: Buffer.from('# 第一章\n图片检查第一段。\n\n第二段。', 'utf-8') });
await page.locator('#import-book-title').fill('图片检查书');
await page.getByRole('button', { name: '导入并放上书架' }).click();
await page.getByRole('button', { name: /书脊：图片检查书/ }).waitFor({ timeout: 15000 });
const books = (await (await page.request.get(BASE + `/api/books?sharecode=${CODE}`)).json()).items;
const target = books.find((b) => b.title === '图片检查书');
await page.goto(`${BASE}/?sharecode=${CODE}#book/${target.id}`, { waitUntil: 'domcontentloaded' });
await page.getByRole('heading', { name: '图片检查书' }).waitFor({ timeout: 20000 });
await page.getByRole('tab', { name: '今天读到这里' }).click();
const selects = page.locator('.record-form select');
await selects.nth(0).selectOption({ index: 0 });
await selects.nth(1).selectOption({ index: 1 });
await page.locator('.context-field textarea').fill('图片加载检查');
await page.locator('.context-photo-field input[type="file"]').setInputFiles(path.join(root, 'artifacts', '07-cloud-service.png'));
await page.locator('.confirm-line input').first().check();
await page.getByRole('button', { name: '保存阅读会话' }).click();
await page.waitForSelector('.timeline-photos img', { timeout: 60000 });
await page.waitForFunction(() => {
  const img = document.querySelector('.timeline-photos img');
  return img && img.complete;
}, { timeout: 20000 }).catch(() => console.log('img_not_complete'));
const info = await page.evaluate(() => {
  const img = document.querySelector('.timeline-photos img');
  return img ? { complete: img.complete, naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight, srcHead: img.src.slice(0, 60) } : null;
});
console.log('img_info=', JSON.stringify(info));
await page.getByRole('button', { name: '删除这本书' }).click();
await page.waitForSelector('.library-page', { timeout: 20000 });
console.log('cleanup=ok');
await browser.close();
