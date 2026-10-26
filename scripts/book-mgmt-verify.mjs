// 线上验证：修改书名、删除整本书、阅读情境照片（云端身份）。
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
await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });

const authCard = page.locator('.auth-card');
if (await authCard.waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)) {
  await page.getByLabel('用户名').fill('persistence-probe-20261025');
  await page.getByLabel('密码').fill('ProbePassword-2026');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.getByText('persistence-probe-20261025', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}

// 1) 导入一本一次性测试书，用于改名与删除验证。
if (!(await page.getByRole('button', { name: /书脊：待整理的书/ }).isVisible().catch(() => false))) {
  await page.getByRole('button', { name: '添加一本书' }).click();
  await page.locator('#book-file').setInputFiles({ name: 'mgmt.txt', mimeType: 'text/plain', buffer: Buffer.from('# 第一章 测试\n第一段内容。\n\n第二段内容。', 'utf-8') });
  await page.locator('#import-book-title').fill('待整理的书');
  await page.getByRole('button', { name: '导入并放上书架' }).click();
  await page.getByRole('button', { name: /书脊：待整理的书/ }).waitFor({ timeout: 15000 });
}
console.log('import=ok');

// 2) 书架封面卡改书名。
await page.getByRole('button', { name: /书脊：待整理的书/ }).click();
await page.getByTestId('cover-card').waitFor();
await page.getByRole('button', { name: '修改书名' }).click();
await page.getByRole('textbox', { name: '书名', exact: true }).fill('整理好的书');
await page.getByRole('button', { name: '保存书名' }).click();
await page.getByRole('button', { name: /书脊：整理好的书/ }).waitFor({ timeout: 15000 });
console.log('rename_in_shelf=ok');

// 3) 手账里改书名 + 保存带照片的阅读情境。
await page.getByRole('button', { name: /书脊：整理好的书/ }).click();
await page.getByRole('button', { name: '进入手账' }).click();
await page.getByRole('heading', { name: '整理好的书' }).waitFor();
await page.getByRole('button', { name: '改书名' }).click();
await page.getByRole('textbox', { name: '书名', exact: true }).fill('手账里改好的书');
await page.getByRole('button', { name: '保存书名' }).click();
await page.getByRole('heading', { name: '手账里改好的书' }).waitFor({ timeout: 15000 });
console.log('rename_in_journal=ok');

await page.getByRole('tab', { name: '今天读到这里' }).click();
const selects = page.locator('.record-form select');
await selects.nth(0).selectOption({ index: 0 });
await selects.nth(1).selectOption({ index: 1 });
await page.locator('.context-field textarea').fill('在宿舍窗边，桌上摊着书，旁边是一杯热茶。');
await page.locator('.context-photo-field input[type="file"]').setInputFiles(path.join(root, 'artifacts', '07-cloud-service.png'));
await page.locator('.confirm-line input').first().check();
await page.getByRole('button', { name: '保存阅读会话' }).click();
await page.waitForSelector('.timeline-photos img', { timeout: 60000 });
const photoCount = await page.locator('.timeline-photos img').count();
const contextText = await page.locator('.timeline-context').first().textContent();
console.log('context_photo_imgs=', photoCount, 'context_text=', (contextText || '').slice(0, 24));
await page.screenshot({ path: path.join(root, 'artifacts', '09-book-management.png'), fullPage: true });

// 4) 删除整本书（浏览器自动接受 confirm）。
await page.getByRole('button', { name: '删除这本书' }).click();
await page.waitForSelector('.library-page', { timeout: 20000 });
const gone = await page.getByRole('button', { name: /书脊：手账里改好的书/ }).waitFor({ state: 'detached', timeout: 20000 }).then(() => true).catch(() => false);
console.log('delete_ok=', gone);

await browser.close();
