"""Validate launch settings without printing credential values."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path


REJECTED_PASSWORDS = {"admin123", "password", "changeme", "change-me", "change_me", "your_password", "change-me-now", "changeme12345"}


def validate_config(config: Mapping[str, str | None]) -> int:
    username = (config.get("WEB_USERNAME") or "").strip()
    password = config.get("WEB_PASSWORD") or ""
    if not username:
        raise ValueError("請設定 WEB_USERNAME，不可留白。")
    if len(password.strip()) < 12 or password.lower() in REJECTED_PASSWORDS:
        raise ValueError("請設定至少 12 字元的自訂 WEB_PASSWORD，不可使用範例或舊版預設密碼。")
    try:
        port = int(config.get("SERVER_PORT") or "8000")
    except (TypeError, ValueError) as exc:
        raise ValueError("SERVER_PORT 必須是 1 至 65535 的整數。") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SERVER_PORT 必須是 1 至 65535 的整數。")
    return port


def main() -> int:
    parser = argparse.ArgumentParser(description="檢查本機啟動設定，不輸出機密值。")
    parser.add_argument("--port", action="store_true", help="只顯示通過驗證的連接埠")
    args = parser.parse_args()
    try:
        from dotenv import dotenv_values
    except ImportError:
        print("尚未安裝 python-dotenv；請先執行啟動腳本以安裝依賴。", file=sys.stderr)
        return 1
    if not Path(".env").is_file():
        print("找不到 .env；請複製 .env.example 並設定登入帳號與密碼。", file=sys.stderr)
        return 1
    config = {**os.environ, **{key: value for key, value in dotenv_values(".env", interpolate=False).items() if value is not None}}
    try:
        port = validate_config(config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(port if args.port else "設定檢查通過。未顯示任何密碼、API Key 或 Webhook。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
