import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const candidates = process.platform === 'win32'
  ? [process.env.PYTHON, path.join(root, '.venv', 'Scripts', 'python.exe'), 'py', 'python']
  : [process.env.PYTHON, path.join(root, '.venv', 'bin', 'python'), 'python3', 'python'];
const executable = candidates.find((item) => item && (item === 'py' || item === 'python' || item === 'python3' || existsSync(item)));
if (!executable) {
  console.error('未找到 Python。请先运行 scripts/install.py，或用 PYTHON 指定解释器。');
  process.exit(1);
}
const args = executable === 'py' ? ['-3', ...process.argv.slice(2)] : process.argv.slice(2);
const child = spawn(executable, args, { stdio: 'inherit', cwd: root, env: process.env });
child.on('error', (error) => {
  console.error(`Python 启动失败：${error.message}`);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 1));
