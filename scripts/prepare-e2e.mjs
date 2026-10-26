import { mkdirSync, rmSync } from 'node:fs';

import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const directory = path.join(root, 'data', 'e2e');
mkdirSync(directory, { recursive: true });
// 仅清理明确命名的自动化测试数据库，不触碰应用数据库或其他个人文件。
for (const name of ['e2e.sqlite3', 'auth.sqlite3']) {
  for (const suffix of ['', '-wal', '-shm']) {
    rmSync(path.join(directory, `${name}${suffix}`), { force: true });
  }
}
rmSync(path.join(directory, 'users'), { recursive: true, force: true });
rmSync(path.join(directory, 'photos'), { recursive: true, force: true });
