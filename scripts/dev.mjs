import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backendOnly = process.argv.includes('--backend-only');
const frontendOnly = process.argv.includes('--frontend-only');
const children = [];

function pythonPath() {
  const local = process.platform === 'win32'
    ? path.join(root, '.venv', 'Scripts', 'python.exe')
    : path.join(root, '.venv', 'bin', 'python');
  return process.env.PYTHON || (existsSync(local) ? local : 'python');
}

function launch(command, args, cwd, label) {
  const child = spawn(command, args, { cwd, env: process.env, stdio: 'inherit' });
  children.push(child);
  child.on('error', (error) => {
    console.error(`[${label}] 启动失败：${error.message}`);
    shutdown(1);
  });
  child.on('exit', (code) => {
    if (code && !shuttingDown) {
      console.error(`[${label}] 异常退出，代码 ${code}`);
      shutdown(code);
    }
  });
}

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) child.kill();
  setTimeout(() => process.exit(code), 150);
}
process.on('SIGINT', () => shutdown());
process.on('SIGTERM', () => shutdown());

if (!frontendOnly) {
  const port = process.env.YUEJI_PORT || '8000';
  launch(pythonPath(), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], path.join(root, 'backend'), 'FastAPI');
}
if (!backendOnly) {
  const vite = path.join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js');
  if (!existsSync(vite)) {
    console.error('缺少前端依赖，请先运行安装脚本。');
    shutdown(1);
  } else {
    launch(process.execPath, [vite, '--host', '127.0.0.1', '--port', process.env.VITE_PORT || '5173'], path.join(root, 'frontend'), 'Vite');
  }
}
if (!backendOnly && !frontendOnly) {
  const backendPort = process.env.YUEJI_PORT || '8000';
  const frontendPort = process.env.VITE_PORT || '5173';
  console.log(`阅迹已启动：前端 http://127.0.0.1:${frontendPort} ，后端 http://127.0.0.1:${backendPort}/docs`);
}
