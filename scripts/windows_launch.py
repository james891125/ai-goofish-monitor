"""Local-only launcher support, reached only through a permitted start.ps1.

No PowerShell policy changes, shell command construction, login, or external HTTP.
The module is standard-library-only so duplicate launches need no installation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
import webbrowser

APPLICATION = "shopee_tw_monitor"
FREE, READY, OCCUPIED = "free", "ready", "occupied"


def configured_port(root: Path) -> int:
    """Read only SERVER_PORT, never log or interpret the rest of .env.

    Support the ordinary dotenv forms for this numeric setting. Fail closed on
    exotic/multiline values instead of guessing a different port.
    """
    value = os.environ.get("SERVER_PORT", "8000")
    for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?SERVER_PORT\s*=\s*(.*)$", line)
        if not match:
            continue
        raw = match.group(1).strip()
        match = re.fullmatch(r'''(?:([0-9]+)|"([0-9]*)"|'([0-9]*)'|)(?:\s+#.*)?''', raw)
        if not match:
            raise ValueError("SERVER_PORT 必須是 1 至 65535 的整數。")
        value = next((part for part in match.groups() if part is not None), "")
    value = value or "8000"
    if not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= 65535:
        raise ValueError("SERVER_PORT 必須是 1 至 65535 的整數。")
    return int(value)


def probe(port: int) -> str:
    """Exact HTTP health contract; no proxy, credentials, or redirects.

    A malformed/nonmatching/redirecting endpoint is occupied, not our app.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except ConnectionRefusedError:
        return FREE
    except OSError:
        # Network restrictions/timeouts are not evidence that a port is free.
        return OCCUPIED
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return OCCUPIED
        body = response.read(4097)
        if len(body) > 4096:
            return OCCUPIED
        result = json.loads(body.decode("utf-8"))
        if (isinstance(result, dict) and result.get("status") == "healthy"
                and result.get("application") == APPLICATION):
            return READY
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return OCCUPIED


def open_app(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    print(f"應用程式已就緒：{url}", flush=True)
    try:
        opened = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        print("無法自動開啟瀏覽器，請自行開啟上方本機網址。", flush=True)


def existing(root: Path, *, open_browser: bool = True, port: int | None = None) -> int:
    port = configured_port(root) if port is None else port
    status = probe(port)
    if status == READY:
        print("已有本系統在此連接埠執行，可能是其他資料夾的版本；不會重複安裝或啟動。升級請先停止舊視窗。", flush=True)
        if open_browser:
            open_app(port)
        return 0
    if status == OCCUPIED:
        print("設定的本機連接埠已被其他程式使用，或服務尚未就緒。未啟動、未關閉任何程式；請先查看原視窗。", flush=True)
        return 4
    return 3


def _stop_child(process: subprocess.Popen) -> None:
    """Stop only the process we created, never a process found on the port."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        # The child has its own process group; do not broadcast to other apps.
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def supervise(root: Path, port: int, *, open_browser: bool, timeout: float = 60) -> int:
    status = probe(port)
    if status == READY:
        if open_browser:
            open_app(port)
        return 0
    if status != FREE:
        print("本機連接埠已被占用；未關閉任何既有程式。", flush=True)
        return 4
    arguments = [sys.executable, "-m", "uvicorn", "src.app:app", "--host", "127.0.0.1",
                 "--port", str(port), "--env-file", ".env"]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(arguments, cwd=root, creationflags=flags)
    print("正在等待本機服務就緒。請保留此視窗查看記錄；按 Ctrl+C 停止。", flush=True)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print("伺服器未能啟動，請查看上方錯誤訊息。", flush=True)
                return process.returncode or 1
            if probe(port) == READY:
                if process.poll() is not None:
                    return process.returncode or 1
                if open_browser:
                    open_app(port)
                else:
                    print(f"請開啟 http://127.0.0.1:{port}", flush=True)
                return process.wait()
            time.sleep(0.25)
        print("等待服務就緒逾時，已停止本次啟動的服務。請查看上方錯誤訊息。", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n正在停止本次啟動的服務。", flush=True)
        return 0
    finally:
        _stop_child(process)


def fresh_output(root: Path) -> Path:
    # Collector's atomic write_result still enforces no-overwrite at write time.
    while True:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = root / f"browser-results-{stamp}-{uuid.uuid4().hex[:8]}.json"
        if not path.exists() and not path.is_symlink():
            return path


def choose_request(root: Path) -> Path | None:
    """Native file picker when available, literal path input otherwise."""
    try:
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        try:
            selection = filedialog.askopenfilename(
                title="選擇已準備好的 browser-request JSON 檔案", initialdir=str(root),
                filetypes=[("瀏覽需求 JSON", "*.json")], parent=window)
        finally:
            window.destroy()
    except Exception:
        # GUI availability varies in minimal Python installs; never evaluate input.
        # Do not echo the exception: it may contain local user paths.
        selection = input("請輸入既有 browser-request JSON 完整路徑（留白取消）：").strip().strip('"')
    if not selection:
        return None
    path = Path(selection)
    if not path.is_absolute():
        path = root / path
    if not path.is_file() or path.suffix.lower() != ".json":
        raise ValueError("請選擇已存在的 JSON 需求檔，未開始瀏覽。")
    return path


def collect(root: Path) -> int:
    request = choose_request(root)
    if request is None:
        print("已取消，未開啟瀏覽器。", flush=True)
        return 0
    output = fresh_output(root)
    print(f"本批將另存新檔：{output.name}", flush=True)
    print("接下來仍須自行輸入 yes 確認風險，並在瀏覽器手動登入。本工具不會代為登入。", flush=True)
    # Argument list only. Never inject a selected filename into a shell command.
    return subprocess.call([sys.executable, str(root / "scripts" / "browser_collect.py"),
                            "--request", str(request), "--output", str(output),
                            "--channel", "msedge"], cwd=root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows 本機啟動輔助工具")
    parser.add_argument("mode", choices=("existing", "serve", "collect"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.mode == "existing":
            return existing(root, open_browser=args.open_browser, port=args.port)
        if args.mode == "collect":
            return collect(root)
        if args.port is None or not 1 <= args.port <= 65535:
            parser.error("--port 必須是 1 至 65535 的整數")
        return supervise(root, args.port, open_browser=args.open_browser)
    except (OSError, ValueError):
        print("無法讀取啟動設定或執行本機輔助工具。請檢查 .env 的 SERVER_PORT、檔案路徑與權限；未顯示任何機密。", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
