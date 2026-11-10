"""讀寫 .env（只用標準函式庫），設定頁面會用它儲存 AI 與 Webhook 設定。"""
import os
from pathlib import Path

ENV_PATH = Path(os.getenv("SHOPEE_LITE_ENV", ".env"))


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _format(value: str) -> str:
    if value and all(ch.isalnum() or ch in "_./:-" for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env(updates: dict[str, str], path: Path | None = None) -> None:
    """只更新指定的鍵，其他內容原樣保留。"""
    path = path or ENV_PATH
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            lines[index] = f"{key}={_format(remaining.pop(key))}"
    for key, value in remaining.items():
        lines.append(f"{key}={_format(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value
