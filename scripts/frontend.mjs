import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(root, 'frontend');
const command = process.argv[2];
const steps = command === 'build'
  ? [
      [path.join(frontend, 'node_modules', 'typescript', 'bin', 'tsc'), ['--noEmit', '-p', path.join(frontend, 'tsconfig.json')]],
      [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), ['build']],
    ]
  : command === 'test'
    ? [[path.join(frontend, 'node_modules', 'vitest', 'vitest.mjs'), ['run']]]
    : [];

if (!steps.length) {
  console.error('用法：node scripts/frontend.mjs build|test');
  process.exit(1);
}

function run([script, args]) {
  return new Promise((resolve, reject) => {
    if (!existsSync(script)) return reject(new Error(`缺少依赖：${script}`));
    const child = spawn(process.execPath, [script, ...args], { cwd: frontend, stdio: 'inherit', env: process.env });
    child.on('error', reject);
    child.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`前端命令失败，代码 ${code}`)));
  });
}

try {
  for (const step of steps) await run(step);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
