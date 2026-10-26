// 抓取投稿用的界面截图（针对已发布的线上版本）。
// 用法：node scripts/submission-shots.mjs
import { chromium } from '@playwright/test';
import fs from 'node:fs';

const BASE = process.env.YUEJI_BASE_URL || 'http://127.0.0.1:5173';
const CODE = process.env.YUEJI_SHARECODE || '';
const START = CODE ? `${BASE}/?sharecode=${CODE}` : BASE;
const USERNAME = process.env.SHOT_USER || '阅迹读者';
const PASSWORD = process.env.SHOT_PASS || 'YuejiReader-2026';
const OUT = 'artifacts/submission';
fs.mkdirSync(OUT, { recursive: true });

const profile = 'artifacts/submission-profile';
const context = await chromium.launchPersistentContext(profile, {
  channel: 'msedge',
  headless: false,
  viewport: { width: 1440, height: 940 },
  deviceScaleFactor: 2,
});
const page = context.pages()[0] || (await context.newPage());

const shot = async (name) => {
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log('saved', name);
};

await page.goto(START, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(4000);

const loggedIn = await page.locator('nav').isVisible().catch(() => false);
if (!loggedIn) {
  await page.getByRole('tab', { name: '登录' }).click();
  await page.getByLabel('用户名').fill(USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(PASSWORD);
  await shot('01-login');
  await page.getByRole('button', { name: '登录书房' }).click();
  await page.waitForTimeout(3500);
}

await shot('02-bookshelf');

// 打开第一本书的手账
await page.locator('.spine, .shelf-book').first().click().catch(async () => {
  await page.getByText('窗外有座小山').first().click();
});
await page.waitForTimeout(3000);
await shot('03-journal');

try {
  await page.getByRole('button', { name: /记录|添加/ }).first().click();
  await page.waitForTimeout(2500);
  await shot('04-journal-record');
} catch {
  console.log('skip record panel');
}

await page.keyboard.press('Escape').catch(() => {});

// 提问页
await page.getByRole('link', { name: /提问/ }).or(page.getByRole('button', { name: /提问/ })).first().click();
await page.waitForTimeout(3000);
await shot('05-ask');

await context.close();
console.log('DONE');
