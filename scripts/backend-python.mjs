import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backend = path.join(root, 'backend');
const local = process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : path.join(root, '.venv', 'bin', 'python');
const executable = process.env.PYTHON || (existsSync(local) ? local : 'python');
const child = spawn(executable, process.argv.slice(2), {
  cwd: backend,
  stdio: 'inherit',
  env: { ...process.env, PYTHONPATH: backend },
});
child.on('error', (error) => {
  console.error(`Python 启动失败：${error.message}`);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 1));
