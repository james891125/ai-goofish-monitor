"""
一鍵啟動：建立虛擬環境、安裝相依套件、建置前端、設定帳密、啟動服務並開啟瀏覽器。

Windows 請直接雙擊 start.bat；macOS / Linux 執行 `python3 start.py`。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements-runtime.txt"
WEB_UI_DIR = ROOT / "web-ui"
DIST_INDEX = ROOT / "dist" / "index.html"
IS_WINDOWS = os.name == "nt"

sys.path.insert(0, str(ROOT))
import setup_env  # noqa: E402  (只依賴標準函式庫)


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[錯誤] {message}")
    sys.exit(1)


def run(command: list[str], cwd: Path = ROOT) -> None:
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        fail(f"指令執行失敗: {' '.join(command)}")


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def ensure_python_packages() -> None:
    step("檢查 Python 環境")
    if sys.version_info < (3, 10):
        fail("需要 Python 3.10 以上版本，請到 https://www.python.org/downloads/ 安裝。")
    if not venv_python().exists():
        print("第一次執行，建立虛擬環境 .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    # requirements 沒變就不重裝，之後啟動會快很多
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    stamp = VENV_DIR / ".requirements.sha256"
    if stamp.exists() and stamp.read_text().strip() == digest:
        print("Python 套件已是最新。")
        return
    print("安裝 Python 套件（第一次需要幾分鐘）...")
    run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    run([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS), "--quiet"])
    stamp.write_text(digest)


def _latest_mtime(folder: Path) -> float:
    return max((p.stat().st_mtime for p in folder.rglob("*") if p.is_file()), default=0.0)


def frontend_needs_build() -> bool:
    if not DIST_INDEX.exists():
        return True
    built_at = DIST_INDEX.stat().st_mtime
    sources = [WEB_UI_DIR / "src", WEB_UI_DIR / "index.html", WEB_UI_DIR / "package.json"]
    for source in sources:
        if source.is_dir() and _latest_mtime(source) > built_at:
            return True
        if source.is_file() and source.stat().st_mtime > built_at:
            return True
    return False


def ensure_frontend() -> None:
    step("檢查前端介面")
    if not frontend_needs_build():
        print("前端已建置。")
        return
    npm = shutil.which("npm")
    if not npm:
        fail("找不到 Node.js / npm，請到 https://nodejs.org/ 安裝 LTS 版本後再執行一次。")
    if not (WEB_UI_DIR / "node_modules").exists():
        print("安裝前端套件（第一次需要幾分鐘）...")
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=WEB_UI_DIR)
    print("建置前端...")
    run([npm, "run", "build"], cwd=WEB_UI_DIR)
    if not DIST_INDEX.exists():
        fail("前端建置失敗，沒有產生 dist/index.html。")


def _browser_installed(names: list[str], windows_paths: list[str], mac_app: str) -> bool:
    if IS_WINDOWS:
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        return any((Path(root) / rel).exists() for root in roots if root for rel in windows_paths)
    if sys.platform == "darwin":
        return Path(mac_app).exists()
    return any(shutil.which(name) for name in names)


def ensure_browser() -> None:
    step("檢查瀏覽器")
    has_chrome = _browser_installed(
        ["google-chrome", "google-chrome-stable"],
        ["Google/Chrome/Application/chrome.exe"],
        "/Applications/Google Chrome.app",
    )
    has_edge = _browser_installed(
        ["microsoft-edge", "microsoft-edge-stable"],
        ["Microsoft/Edge/Application/msedge.exe"],
        "/Applications/Microsoft Edge.app",
    )
    values = setup_env.read_env()
    if has_chrome:
        print("找到 Chrome。")
    elif has_edge:
        print("沒有找到 Chrome，改用 Edge。")
        if values.get("LOGIN_IS_EDGE", "").lower() != "true":
            setup_env.write_env({"LOGIN_IS_EDGE": "true"})
    else:
        print("[警告] 沒有找到 Chrome 或 Edge，爬蟲任務會無法執行。請先安裝 Google Chrome。")


def server_url() -> str:
    port = setup_env.read_env().get("SERVER_PORT", "").strip() or "8000"
    return f"http://127.0.0.1:{port}"


def wait_until_ready(url: str, process: subprocess.Popen, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


def start_server() -> int:
    url = server_url()
    step(f"啟動服務 {url}")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([str(venv_python()), "-m", "src.app"], cwd=ROOT, env=env)
    try:
        if wait_until_ready(url, process):
            print(f"\n服務已啟動，請用瀏覽器開啟: {url}")
            print("要停止服務請在這個視窗按 Ctrl+C，或直接關閉視窗。\n")
            if os.environ.get("SHOPEE_MONITOR_NO_BROWSER") != "1":
                webbrowser.open(url)
        elif process.poll() is not None:
            fail("服務啟動失敗，請查看上方的錯誤訊息。")
        return process.wait()
    except KeyboardInterrupt:
        print("\n正在停止服務...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0


def main() -> int:
    os.chdir(ROOT)
    print("蝦皮智慧監控 - 一鍵啟動")
    ensure_python_packages()
    ensure_frontend()
    step("檢查設定檔 .env")
    if setup_env.main() != 0:
        return 1
    ensure_browser()
    return start_server()


if __name__ == "__main__":
    raise SystemExit(main())
