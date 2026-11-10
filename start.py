"""
一鍵啟動：建立 .venv、安裝套件、開啟網頁介面。

Windows 請直接雙擊 start.bat；macOS / Linux 執行 `python3 start.py`。
"""
import hashlib
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(command: list[str]) -> None:
    if subprocess.run(command, cwd=ROOT).returncode != 0:
        print(f"\n[錯誤] 指令失敗: {' '.join(command)}")
        sys.exit(1)


def main() -> int:
    print("蝦皮商品清單 - 一鍵啟動")
    if sys.version_info < (3, 10):
        print("[錯誤] 需要 Python 3.10 以上，請到 https://www.python.org/downloads/ 安裝。")
        return 1
    if not PYTHON.exists():
        print("第一次執行，建立虛擬環境 .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    stamp = VENV / ".requirements.sha256"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text().strip() != digest:
        print("安裝套件（第一次需要一兩分鐘）...")
        run([str(PYTHON), "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)])
        stamp.write_text(digest)
    # 繼續把額外參數（例如 --port 9000）傳給介面
    return subprocess.run([str(PYTHON), "-m", "shopee_lite", "ui", *sys.argv[1:]], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
