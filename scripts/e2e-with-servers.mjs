import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const node = process.execPath;
const backendPort = process.env.YUEJI_E2E_BACKEND_PORT || '48123';
const frontendPort = process.env.YUEJI_E2E_FRONTEND_PORT || '53124';
const children = [];

function run(script, args = [], env = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(node, [path.join(root, script), ...args], {
      cwd: root,
      env: { ...process.env, ...env },
      stdio: 'inherit',
    });
    children.push(child);
    child.on('error', reject);
    child.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`${path.basename(script)} 失败，代码 ${code}`)));
  });
}

function spawnServer(script, args, env) {
  const child = spawn(node, [path.join(root, script), ...args], {
    cwd: root,
    env: { ...process.env, ...env },
    stdio: 'inherit',
  });
  children.push(child);
  child.on('error', (error) => {
    console.error(error.message);
    shutdown(1);
  });
  return child;
}

function waitFor(url, label) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      const request = http.get(url, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) return resolve();
        retry();
      });
      request.on('error', retry);
      request.setTimeout(1200, () => request.destroy());
      function retry() {
        if (Date.now() - started > 90_000) return reject(new Error(`等待${label}超时：${url}`));
        setTimeout(tick, 500);
      }
    };
    tick();
  });
}

function shutdown(code = 0) {
  for (const child of children) {
    try { child.kill(); } catch { /* already exited */ }
  }
  setTimeout(() => process.exit(code), 150);
}

process.on('SIGINT', () => shutdown(130));
process.on('SIGTERM', () => shutdown(143));

try {
  await run('scripts/prepare-e2e.mjs');
  spawnServer('scripts/dev.mjs', ['--backend-only'], {
    YUEJI_DATA_DIR: './data/e2e',
    YUEJI_DATABASE: 'e2e.sqlite3',
    YUEJI_SEED_SAMPLES: 'true',
    YUEJI_AUTH_REQUIRED: 'true',
    YUEJI_TEST_INVITE_CODE: 'E2E-INVITE-2026',
    YUEJI_MASTER_KEY: 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=',
    YUEJI_PORT: backendPort,
  });
  await waitFor(`http://127.0.0.1:${backendPort}/api/health`, '后端');
  spawnServer('scripts/dev.mjs', ['--frontend-only'], {
    VITE_PORT: frontendPort,
    YUEJI_API_TARGET: `http://127.0.0.1:${backendPort}`,
  });
  await waitFor(`http://127.0.0.1:${frontendPort}`, '前端');
  const cli = path.join(root, 'node_modules', '@playwright', 'test', 'cli.js');
  const rawArgs = process.argv.slice(2);
  const userArgs = rawArgs[0] === '--' ? rawArgs.slice(1) : rawArgs;
  const cliArgs = userArgs.length === 0 || userArgs[0].startsWith('-') ? ['test', ...userArgs] : userArgs;
  const testRun = spawn(node, [cli, ...cliArgs], { cwd: root, stdio: 'inherit', env: process.env });
  children.push(testRun);
  testRun.on('exit', (code) => shutdown(code ?? 1));
} catch (error) {
  console.error(error.message);
  shutdown(1);
}
