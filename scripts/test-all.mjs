import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function run(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], { cwd: root, stdio: 'inherit', env: process.env });
    child.on('error', reject);
    child.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`测试失败：${path.basename(script)}`)));
  });
}
try {
  await run(path.join(root, 'scripts', 'python.mjs'), ['-m', 'pytest', 'backend/tests', '-q']);
  await run(path.join(root, 'scripts', 'frontend.mjs'), ['test']);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
