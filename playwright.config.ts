import { defineConfig } from '@playwright/test';

// E2E 服务由 scripts/e2e-with-servers.mjs 启动，避免本机代理对未绑定端口返回 502 导致误判端口占用。
export default defineConfig({
  testDir: 'frontend/tests',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  outputDir: `test-results-run-${Date.now()}`,
  use: {
    baseURL: 'http://127.0.0.1:53124',
    browserName: 'chromium',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'off',
  },
});
