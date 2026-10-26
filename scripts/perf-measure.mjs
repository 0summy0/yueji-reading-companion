// 性能测量：900 段的长书，比较“进入手账到可交互”的耗时与下拉选项数量。
import { chromium } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = 'http://127.0.0.1:5191';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage();
await page.goto(base, { waitUntil: 'domcontentloaded' });

const imported = await page.request.post(base + '/api/books/import', {
  multipart: { file: { name: 'perf-book.txt', mimeType: 'text/plain', buffer: (await import('node:fs')).readFileSync(path.join(root, 'artifacts', 'perf-book.txt')) }, title: '性能测试书' },
});
const book = (await imported.json()).book;
const passages = (await (await page.request.get(`${base}/api/books/${book.id}/passages`)).json()).items.length;
console.log('passages=', passages);

// 进入手账：从点击到段落选择器可交互的耗时
const start = Date.now();
await page.goto(`${base}/#book/${book.id}`, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.passage-picker select', { timeout: 30000 });
const interactive = Date.now() - start;
console.log('journal_interactive_ms=', interactive);

const selectCount = await page.locator('.passage-picker select').count();
const optionCount = await page.locator('.passage-picker option').count();
console.log('picker_selects=', selectCount, 'picker_options=', optionCount, 'old_style_options_would_be=', passages * 3);

// 打字延迟：在阅读情境内输入 30 个字，测总耗时
await page.getByRole('tab', { name: '今天读到这里' }).click();
const typingStart = Date.now();
await page.locator('.context-field textarea').pressSequentially('在图书馆靠窗的位置，下午的光线斜进来，旁边有人翻书。', { delay: 0 });
const typingMs = Date.now() - typingStart;
console.log('typing_30_chars_ms=', typingMs);

await page.screenshot({ path: path.join(root, 'artifacts', '10-passage-picker.png'), fullPage: true });
await browser.close();
