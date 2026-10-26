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
await page.goto(`${BASE}/?sharecode=${CODE}#/cloud`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(4000);
const text = await page.locator('.cloud-card').nth(2).textContent().catch(() => '');
console.log('cloud_card_3=', (text || '').replace(/\s+/g, ' ').slice(0, 200));
await browser.close();
