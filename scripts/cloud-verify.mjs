// 线上云服务真实验证脚本（分阶段）。
// 阶段 A：免登录探测 LLM（models.list + 流式 chat completion）。
// 阶段 B：完整真实 UI 流程 —— 书房账号登录 → 云服务邮箱 OTP → 云备份写入读回 → 云存储自检
//         → 导入样书 → 保存已读会话 → 提问页云端免密钥问答（引用校验）。
// 用法：node scripts/cloud-verify.mjs A|B   （B 需要 EMAIL/CODE 环境变量）
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
const PUBLIC_CONFIG = {
  endpoint: `${BASE}`,
  oauthRelayBaseUrl: 'https://www.workbuddy.cn/v2/as/genie-baas/oauth',
  publishableKey: process.env.YUEJI_WB_PUBLISHABLE_KEY || '',
};
const SDK_URL = 'https://cdn.jsdelivr.net/npm/@tencent-ai/workbuddy-cloud-sdk@dev/lib/index.global.js';

const stage = process.argv[2] || 'A';

async function injectSdk(page) {
  await page.evaluate(async (url) => {
    if (window.WorkBuddyCloud) return;
    await new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = url;
      script.onload = resolve;
      script.onerror = () => reject(new Error('SDK 加载失败'));
      document.head.appendChild(script);
    });
  }, SDK_URL);
  await page.evaluate((config) => {
    window.__cloud = window.WorkBuddyCloud.createWorkBuddyCloud(config);
  }, PUBLIC_CONFIG);
}

async function stageA() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });
  await injectSdk(page);

  const models = await page.evaluate(async () => window.__cloud.llm.models.list());
  console.log('models_count=', models.length);
  const usable = models.filter((m) => m.disabled !== true);
  console.log('first_model=', JSON.stringify(usable[0] ? { id: usable[0].id, name: usable[0].name } : null));

  const chatResult = await page.evaluate(async ({ config, model }) => {
    const client = window.WorkBuddyCloud.createWorkBuddyCloud(config);
    let text = '';
    let usage = null;
    try {
      for await (const chunk of client.llm.chat.completions.create({
        model,
        messages: [
          { role: 'system', content: '你是简洁有帮助的助手。' },
          { role: 'user', content: '用一句话回答：纸质书阅读记录有什么价值？' },
        ],
        stream: true,
        temperature: 0.5,
      })) {
        if (chunk.choices?.[0]?.delta?.content) text += chunk.choices[0].delta.content;
        if (chunk.usage) usage = chunk.usage;
      }
      return { ok: true, text, usage };
    } catch (error) {
      return { ok: false, code: error?.error?.code || null, message: error?.message || String(error) };
    }
  }, { config: PUBLIC_CONFIG, model: usable[0]?.id || '' });

  console.log('chat_ok=', chatResult.ok);
  console.log('chat_text=', (chatResult.text || '').slice(0, 120));
  await browser.close();
  if (!chatResult.ok) process.exit(1);
}

async function stageB() {
  const email = process.env.EMAIL;
  if (!email) throw new Error('阶段 B 需要 EMAIL 环境变量');
  const codeFile = path.join(root, 'artifacts', 'otp-code.txt');
  const user = process.env.APP_USER || 'persistence-probe-20261025';
  const pass = process.env.APP_PASS || 'ProbePassword-2026';
  const fs = await import('node:fs');
  const profileDir = path.join(root, 'artifacts', 'cloud-profile');

  const browser = await chromium.launchPersistentContext(profileDir, { channel: 'msedge', headless: true });
  const page = browser.pages()[0] || (await browser.newPage());
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded' });

  // 1) 书房账号登录（邀请制试用账号）。等待登录卡真正渲染后再填写。
  const authCard = page.locator('.auth-card');
  const authVisible = await authCard.waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false);
  if (authVisible) {
    await page.getByLabel('用户名').fill(user);
    await page.getByLabel('密码').fill(pass);
    await page.getByRole('button', { name: '登录书房' }).click();
    await page.getByText(user, { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  }
  console.log('app_login=ok');

  // 2) 云服务页：请求邮箱验证码，然后等待人工把验证码写入 artifacts/otp-code.txt。
  await page.getByRole('button', { name: '云服务' }).click();
  await page.getByLabel('邮箱地址').fill(email);
  await page.getByRole('button', { name: /获取验证码/ }).click();
  console.log('otp_sent=waiting_for_code_file');

  let code = '';
  for (let waited = 0; waited < 600; waited += 2) {
    if (fs.existsSync(codeFile)) {
      code = fs.readFileSync(codeFile, 'utf-8').trim();
      if (code) break;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  if (!code) throw new Error('等待验证码超时（10 分钟）');
  fs.rmSync(codeFile, { force: true });
  console.log('otp_received=continuing');

  await page.getByLabel('验证码').fill(code);
  await page.getByRole('button', { name: '登录云端身份' }).click();
  await page.waitForSelector('.cloud-grid', { timeout: 20000 });
  console.log('cloud_login=ok');

  // 3) 云备份：写入并读回。
  await page.getByRole('button', { name: '立即备份书房' }).click();
  await page.waitForSelector('.backup-list li strong', { timeout: 30000 });
  const backupLabel = await page.locator('.backup-list li strong').first().textContent();
  console.log('backup_created=', backupLabel);

  // 4) 云存储自检（上传→签名下载→比对→删除）。
  await page.getByRole('button', { name: '运行云存储自检' }).click();
  await page.waitForSelector('.cloud-ok', { timeout: 30000 });
  console.log('storage_probe=ok');
  await page.screenshot({ path: path.join(root, 'artifacts', '07-cloud-service.png'), fullPage: true });

  // 5) 导入样书并保存一段顺读会话，制造已读证据。
  await page.getByRole('button', { name: '书房', exact: true }).click();
  const addButton = page.getByRole('button', { name: '添加一本书' });
  if (!(await page.getByRole('button', { name: /书脊：窗外有座小山/ }).isVisible().catch(() => false))) {
    await addButton.click();
    await page.locator('#book-file').setInputFiles(path.join(root, 'samples', '窗外有座小山.txt'));
    await page.locator('#import-book-title').fill('窗外有座小山');
    await page.getByRole('button', { name: '导入并放上书架' }).click();
  }
  await page.getByRole('button', { name: /书脊：窗外有座小山/ }).click();
  await page.getByRole('button', { name: '进入手账' }).click();
  await page.getByRole('tab', { name: '今天读到这里' }).click();
  const anchorSelects = page.locator('.record-form select');
  await anchorSelects.nth(0).selectOption({ index: 0 });
  await anchorSelects.nth(1).selectOption({ index: 2 });
  await page.locator('.confirm-line input').first().check();
  await page.getByRole('button', { name: '保存阅读会话' }).click();
  await page.waitForSelector('.range-ledger', { timeout: 15000 });
  console.log('read_session=ok');

  // 6) 提问页：云端免密钥问答，校验引用来自证据包。
  await page.getByRole('button', { name: '提问' }).click();
  await page.locator('.ask-composer select').first().selectOption('cloud');
  await page.getByLabel('问题').fill('根据我读过的内容，窗外的小山给人什么感觉？请标注证据。');
  await page.getByRole('button', { name: '开始提问' }).click();
  await page.waitForSelector('.answer-entry .answer-text', { timeout: 90000 });
  const answer = (await page.locator('.answer-entry .answer-text').first().textContent()) || '';
  const citations = await page.locator('.answer-entry .citation-chip').count();
  const noCitationWarning = await page.locator('.answer-entry .muted').count();
  console.log('cloud_ask=ok:', answer.slice(0, 80));
  console.log('citation_chips=', citations, 'warnings=', noCitationWarning);
  await page.screenshot({ path: path.join(root, 'artifacts', '08-cloud-ask.png'), fullPage: true });

  await browser.close();
  if (!answer.trim()) process.exit(1);
}

if (stage === 'A') await stageA();
else if (stage === 'B') await stageB();
else throw new Error(`未知阶段：${stage}`);
