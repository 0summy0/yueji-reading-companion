// 线上验证：新版分层选择 + 加载提示（延迟接口以观察 spinner）。
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
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage();
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
  multipart: { file: { name: 'perf-live-v2.txt', mimeType: 'text/plain', buffer: fs.readFileSync(path.join(root, 'artifacts', 'perf-book.txt')) }, title: '性能对比书V2' },
});
const book = (await imported.json()).book;

// 1) 延迟手账接口，确认加载提示真实可见
await page.route(new RegExp(`/api/books/${book.id}(\\?|$)`), async (route) => {
  await new Promise((resolve) => setTimeout(resolve, 2500));
  await route.continue();
});
const start = Date.now();
await page.goto(`${BASE}/?sharecode=${CODE}#book/${book.id}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.loading-ring', { timeout: 5000 });
const loadingText = (await page.locator('.journal-loading').innerText()).replace(/\s+/g, ' ');
console.log('loading_visible=', loadingText.slice(0, 40));
await page.screenshot({ path: path.join(root, 'artifacts', '11-journal-loading.png') });
await page.waitForSelector('.passage-picker select', { timeout: 30000 });
const interactive = Date.now() - start - 2500;
console.log('journal_interactive_ms=', interactive);

// 2) 分层选择：章节数、选项数、切章后仍可正常选择
const chapterSelect = page.locator('.passage-picker select').nth(0);
const passageSelect = page.locator('.passage-picker select').nth(1);
console.log('chapter_options=', await chapterSelect.locator('option').count(), 'passage_options=', await passageSelect.locator('option').count());
const totalOptions = await page.locator('.record-form option').count();
console.log('total_options_now=', totalOptions);
await chapterSelect.selectOption({ index: 12 }); // 第 13 章
await passageSelect.selectOption({ index: 5 });
const hint = await page.locator('.passage-picker-hint').first().innerText();
console.log('picker_hint=', hint.replace(/\s+/g, ' '));
await page.screenshot({ path: path.join(root, 'artifacts', '12-passage-picker-live.png'), fullPage: true });

// 3) 清理测试书
await page.getByRole('button', { name: '删除这本书' }).click();
await page.waitForSelector('.library-page', { timeout: 30000 });
console.log('cleanup=ok');
await browser.close();
