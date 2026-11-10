"""
桌面啟動入口
使用 PyInstaller 打包後作為單一可執行檔案的入口，自動啟動 FastAPI 服務並開啟瀏覽器。
"""
import os
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

# PyInstaller 執行時資源目錄：_MEIPASS；未打包時則為目前檔案所在目錄
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _prepare_environment() -> None:
    """確保工作目錄和模組路徑正確"""
    os.chdir(BASE_DIR)
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))


def run_app() -> None:
    """啟動 FastAPI 應用並自動開啟瀏覽器"""
    _prepare_environment()

    from src.app import app
    from src.infrastructure.config.settings import settings

    # 先嚐試開啟瀏覽器，稍等服務起來
    url = f"http://127.0.0.1:{settings.server_port}"
    webbrowser.open(url)
    time.sleep(0.5)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.server_port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run_app()
