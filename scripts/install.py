"""Windows/macOS/Linux 本地依赖安装；不修改系统权限或全局包。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更高版本。")
    if not VENV.exists():
        print("创建项目内 .venv")
        venv.EnvBuilder(with_pip=True).create(VENV)
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-r", "backend/requirements.txt"])
    pnpm = os.getenv("PNPM") or shutil.which("pnpm") or shutil.which("pnpm.cmd")
    npm = os.getenv("NPM") or shutil.which("npm") or shutil.which("npm.cmd")
    corepack = shutil.which("corepack") or shutil.which("corepack.cmd")
    if pnpm:
        package_manager = [pnpm]
    elif npm:
        package_manager = [npm]
    elif corepack:
        package_manager = [corepack, "pnpm"]
    else:
        raise SystemExit("未找到 pnpm/npm/corepack。可将 WORK_ENVIRONMENT.md 中的 pnpm 路径放入 PNPM 环境变量后重试。")
    run([*package_manager, "install"])
    run([*package_manager, "install"], ROOT / "frontend")
    print("\n安装完成。运行 npm run dev（或 pnpm dev），然后打开 http://127.0.0.1:5173")


if __name__ == "__main__":
    main()
