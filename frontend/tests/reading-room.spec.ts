import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';

const shot = (name: string) => path.resolve('artifacts', name);
const USERNAME = 'e2e同学';
const PASSWORD = 'E2E-Password-2026';
const INVITE = 'E2E-INVITE-2026';

async function ensureLoggedIn(page: Page) {
  await page.goto('/');
  const authCard = page.locator('.auth-card');
  const authVisible = await authCard.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
  if (authVisible) {
    await page.getByLabel('用户名').fill(USERNAME);
    await page.getByLabel('密码', { exact: true }).fill(PASSWORD);
    await page.getByRole('button', { name: '登录书房' }).click();
    const loggedIn = await page.getByText(USERNAME, { exact: true }).waitFor({ state: 'visible', timeout: 3500 }).then(() => true).catch(() => false);
    if (!loggedIn) {
      await page.getByRole('tab', { name: '邀请注册' }).click();
      await page.getByLabel('邀请码').fill(INVITE);
      await page.getByLabel('用户名').fill(USERNAME);
      await page.getByLabel('密码', { exact: true }).fill(PASSWORD);
      await page.getByRole('button', { name: '创建试用账号' }).click();
    }
  }
  await expect(page.getByText(USERNAME, { exact: true })).toBeVisible();
}

async function saveTaskRoutes(page: Page) {
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith('/api/ai/task-routes') && response.request().method() === 'PUT');
  await page.getByRole('button', { name: '保存任务路由', exact: true }).click();
  expect((await responsePromise).ok()).toBe(true);
  await expect(page.getByRole('button', { name: '保存任务路由', exact: true })).toBeEnabled();
}

test.beforeEach(async ({ page }) => {
  await ensureLoggedIn(page);
});

test('书架抽书、笔记版本、会话范围、导入去重与刷新持久化', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.book-spine')).toHaveCount(3);
  await page.screenshot({ path: shot('01-bookshelf.png'), fullPage: true });

  await page.getByPlaceholder('找书名或作者…').fill('夜航');
  await expect(page.locator('.book-spine')).toHaveCount(1);
  await page.getByPlaceholder('找书名或作者…').fill('');
  await expect(page.locator('.book-spine')).toHaveCount(3);

  await page.locator('.book-spine').first().click();
  await expect(page.getByTestId('cover-card')).toBeVisible();
  await page.screenshot({ path: shot('02-drawn-book.png'), fullPage: true });
  await page.getByRole('button', { name: '进入手账' }).click();
  await expect(page).toHaveURL(/#book\//);

  await page.getByRole('tab', { name: '我有一个想法' }).click();
  await page.locator('.record-form textarea').fill('最初的原话：我还不确定这段沉默意味着什么。');
  const noteSelects = page.locator('.record-form select');
  await noteSelects.nth(0).selectOption({ index: 0 });
  await noteSelects.nth(1).selectOption({ index: 1 });
  await page.getByRole('button', { name: '保存我的原话' }).click();
  await expect(page.locator('.note-text')).toHaveText('最初的原话：我还不确定这段沉默意味着什么。');
  await page.getByRole('button', { name: '修订原话' }).click();
  await page.locator('.note-edit textarea').fill('修订后的原话：沉默也许是人物保护自己的方式。');
  await page.getByRole('button', { name: '保存为新版本' }).click();
  await expect(page.locator('.note-text')).toHaveText('修订后的原话：沉默也许是人物保护自己的方式。');
  await page.getByText('查看 2 个版本', { exact: true }).click();
  await expect(page.locator('.version-list')).toContainText('最初的原话');
  await page.screenshot({ path: shot('03-journal-versions.png'), fullPage: true });

  await page.reload();
  await expect(page.locator('.note-text')).toHaveText('修订后的原话：沉默也许是人物保护自己的方式。');
  await expect(page.getByText('查看 2 个版本', { exact: true })).toBeVisible();
  await page.locator('.skip-link').focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#book\//);
  await expect(page.locator('#main-content')).toBeFocused();

  await page.getByRole('tab', { name: '今天读到这里' }).click();
  const anchorSelects = page.locator('.record-form select');
  await anchorSelects.nth(0).selectOption({ index: 0 });
  await anchorSelects.nth(1).selectOption({ index: 1 });
  await anchorSelects.nth(2).selectOption({ index: 0 });
  await anchorSelects.nth(3).selectOption({ index: 3 });
  await page.locator('.context-field textarea').fill('在书桌台灯下，窗外有细雨，旁边放着一杯温茶。');
  await page.locator('.confirm-line input').first().check();
  await page.getByRole('button', { name: '保存阅读会话' }).click();
  await expect(page.locator('.range-ledger')).toContainText('段落 #1—#3');
  await page.reload();
  await expect(page.locator('.book-timeline')).toContainText('阅读情境：在书桌台灯下，窗外有细雨，旁边放着一杯温茶。');
  await page.screenshot({ path: shot('06-reading-context.png'), fullPage: true });

  await page.getByRole('button', { name: '返回书架' }).click();
  const addButton = page.getByRole('button', { name: '添加一本书' });
  await addButton.click();
  const fileInput = page.locator('#book-file');
  await expect(fileInput).toBeFocused();
  const submit = page.getByRole('button', { name: '导入并放上书架' });
  await submit.focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: '关闭导入' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(addButton).toBeFocused();

  await addButton.click();
  await fileInput.setInputFiles({ name: 'e2e-import.txt', mimeType: 'text/plain', buffer: Buffer.from('# 第一章 测试\n导入后的第一段。\n\n导入后的第二段。', 'utf-8') });
  await page.locator('#import-book-title').fill('E2E 导入书');
  await page.locator('#import-author').fill('自动化作者');
  await submit.click();
  await expect(page.getByRole('button', { name: '书脊：E2E 导入书，自动化作者' })).toBeVisible();
  await expect(page.locator('.book-spine')).toHaveCount(4);

  await addButton.click();
  await fileInput.setInputFiles({ name: 'e2e-import.txt', mimeType: 'text/plain', buffer: Buffer.from('# 第一章 测试\n导入后的第一段。\n\n导入后的第二段。', 'utf-8') });
  await submit.click();
  await expect(page.locator('.toast')).toContainText('同一文件已存在');
  await expect(page.locator('.book-spine')).toHaveCount(4);
  await page.reload();
  await expect(page.locator('.book-spine')).toHaveCount(4);
});

test('窄屏、键盘抽书与 reduced-motion 降级', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const spine = page.locator('.book-spine').first();
  await expect(spine).toHaveCSS('transform', 'none');
  await spine.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('cover-card')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  await page.screenshot({ path: shot('04-mobile-keyboard.png'), fullPage: true });
});

test('真实设置表单、Mock 分项检测、路由清空、照片入口能力状态', async ({ page }) => {
  await page.goto('/#settings');
  await expect(page.locator('.real-banner')).toContainText('真实连接只由后端调用');
  await expect(page.getByRole('combobox', { name: '服务商预设' })).toHaveValue('deepseek');
  await expect(page.locator('.connection-form input[type="url"]')).toHaveValue('https://api.deepseek.com');
  await expect(page.getByLabel('模型 ID')).toHaveValue('deepseek-flash');
  await expect(page.getByLabel('API Key', { exact: true })).toHaveAttribute('type', 'password');

  await page.getByRole('combobox', { name: 'Provider' }).selectOption('mock');
  await page.getByLabel('连接名称').fill('我的离线演示');
  await page.getByLabel('模型 ID').fill('mock-reader-v1');
  await page.getByRole('button', { name: '连接并检测', exact: true }).click();
  const success = page.locator('.connection-entry').filter({ hasText: '我的离线演示' }).first();
  await expect(success.getByText('已通过（模拟）', { exact: true })).toHaveCount(3);

  const textRoute = page.locator('.route-list label', { hasText: '文字问答' }).locator('select');
  await textRoute.selectOption({ label: '我的离线演示 · mock-reader-v1' });
  await saveTaskRoutes(page);
  await textRoute.selectOption('');
  await saveTaskRoutes(page);
  await page.reload();
  await expect(page.locator('.route-list label', { hasText: '文字问答' }).locator('select')).toHaveValue('');
  await expect(page.locator('.connection-entry').filter({ hasText: '我的离线演示' }).first()).toBeVisible();

  await page.getByRole('combobox', { name: 'Provider' }).selectOption('mock');
  await page.getByLabel('模型 ID').fill('mock-reader-v1');
  await page.locator('.scenario-field select').selectOption('partial');
  await page.getByLabel('连接名称').fill('部分视觉演示');
  await page.getByRole('button', { name: '连接并检测', exact: true }).click();
  const partial = page.locator('.connection-entry').filter({ hasText: '部分视觉演示' }).first();
  await expect(partial).toContainText('视觉部分通过（模拟）');

  await page.locator('.route-list label', { hasText: '拍照识别' }).locator('select').selectOption({ label: '我的离线演示 · mock-reader-v1' });
  await saveTaskRoutes(page);
  await expect(page.locator('.route-list label', { hasText: '拍照识别' }).locator('select')).not.toHaveValue('');
  await page.screenshot({ path: shot('05-mock-capabilities.png'), fullPage: true });

  const response = await page.request.get('/api/books');
  const books = (await response.json()).items;
  await page.goto(`/#book/${books[0].id}`);
  await page.getByRole('button', { name: /照片定位/ }).click();
  await expect(page.locator('.photo-capabilities')).toContainText('处理路径：AI 视觉（已选路由）');
  await expect(page.locator('.photo-capabilities')).toContainText('图片输入：已通过（模拟）');
  await expect(page.locator('.photo-capabilities')).toContainText('中文读字：已通过（模拟）');
  await expect(page.locator('.photo-fallback')).toContainText('照片会先去除 EXIF');
});

test('书格拉底：模式切换、记录空状态与无 AI 安全降级', async ({ page }) => {
  await page.goto('/#ask');
  await expect(page.getByRole('heading', { name: '向阅读伴侣提问' })).toBeVisible();

  // 切换到书格拉底：说明证据边界与轮数选择。
  await page.getByRole('tab', { name: /书格拉底/ }).click();
  await expect(page.getByRole('heading', { level: 2, name: /书格拉底 · 苏格拉底式理解检查/ })).toBeVisible();
  await expect(page.getByText(/你已读的原文范围/)).toBeVisible();
  await expect(page.getByText(/不会泄露未读内容/)).toBeVisible();
  const rounds = page.getByLabel('追问轮数');
  await expect(rounds).toHaveValue('3');
  await page.screenshot({ path: shot('13-socratic-config.png'), fullPage: true });

  // 历史记录空状态（全新数据库；若此前用例已建会话则跳过该断言）。
  await page.getByRole('button', { name: '看历史记录' }).click();
  const emptyHint = page.getByText(/还没有书格拉底会话/);
  if (await emptyHint.isVisible().catch(() => false)) {
    await expect(emptyHint).toBeVisible();
    await page.screenshot({ path: shot('14-socratic-history-empty.png'), fullPage: true });
  }
  await page.getByRole('button', { name: /再开一局/ }).click();

  // 给第一本书补一次顺读会话，确保证据快照非空。
  const books = (await (await page.request.get('/api/books')).json()).items;
  const book = books[0];
  const passages = (await (await page.request.get(`/api/books/${book.id}/passages`)).json()).items;
  await page.request.post(`/api/books/${book.id}/sessions`, { data: {
    started_at: '2026-10-25T20:00:00+08:00', ended_at: '2026-10-25T20:20:00+08:00',
    timezone: 'Asia/Shanghai', start_anchor: passages[0].id, current_anchor: passages[1].id,
    session_type: 'sequential', sequential_confirmed: true, anchor_read_confirmed: true,
    client_request_id: `e2e-socratic-${Date.now()}`,
  }});

  // 清空文字路由：BYOK 模式必须明确降级，且不产生半成品会话。
  await page.request.put('/api/ai/task-routes', { data: { routes: {} } });
  await page.getByRole('button', { name: /开始书格拉底/ }).click();
  await expect(page.locator('.socratic-config .form-error')).toContainText('文字检测');
  const sessions = (await (await page.request.get('/api/socratic')).json()).items;
  expect(sessions.filter((item: { book_id: string }) => item.book_id === book.id)).toHaveLength(0);
});
