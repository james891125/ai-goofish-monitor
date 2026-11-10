"""
首次啟動設定精靈。

檢查 .env 是否存在、Web 登入帳號密碼是否已設定；沒有的話在終端機請使用者輸入並寫入 .env。
只使用標準函式庫，Windows / macOS / Linux 都能直接執行：

    python setup_env.py
"""
from __future__ import annotations

import getpass
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

# 上游專案的預設密碼，視同「尚未設定」
INSECURE_PASSWORDS = {"", "admin123"}
PLACEHOLDER_API_KEYS = {"", "sk-..."}

AI_PROVIDERS = {
    "1": (
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.5-flash",
        "https://aistudio.google.com/apikey",
    ),
    "2": (
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "google/gemini-2.5-flash",
        "https://openrouter.ai/keys",
    ),
    "3": (
        "OpenAI",
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        "https://platform.openai.com/api-keys",
    ),
}


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
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


def _format_value(value: str) -> str:
    if value and all(ch.isalnum() or ch in "_./:-" for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_env(updates: dict[str, str], path: Path = ENV_FILE) -> None:
    """更新指定的鍵，其他內容與註解保持原樣。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            lines[index] = f"{key}={_format_value(remaining.pop(key))}"
    for key, value in remaining.items():
        lines.append(f"{key}={_format_value(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def needs_credentials(values: dict[str, str]) -> bool:
    return (
        not values.get("WEB_USERNAME", "").strip()
        or values.get("WEB_PASSWORD", "").strip() in INSECURE_PASSWORDS
    )


def needs_ai_key(values: dict[str, str]) -> bool:
    return values.get("OPENAI_API_KEY", "").strip() in PLACEHOLDER_API_KEYS


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_password() -> str:
    while True:
        first = getpass.getpass("請設定登入密碼（輸入時畫面不會顯示）: ").strip()
        if len(first) < 6:
            print("  密碼至少需要 6 個字元，請重新輸入。")
            continue
        if first == "admin123":
            print("  這是公開的預設密碼，請換一個。")
            continue
        if getpass.getpass("請再輸入一次密碼: ").strip() != first:
            print("  兩次輸入不一致，請重新輸入。")
            continue
        return first


def prompt_credentials(values: dict[str, str]) -> dict[str, str]:
    print("\n=== 設定 Web 管理介面的登入帳號密碼 ===")
    print("之後用瀏覽器開啟管理介面時，要用這組帳密登入。")
    username = _ask("請設定登入帳號", values.get("WEB_USERNAME", "").strip() or "admin")
    return {"WEB_USERNAME": username, "WEB_PASSWORD": _ask_password()}


def prompt_ai(values: dict[str, str]) -> dict[str, str]:
    print("\n=== 設定 AI 模型（可略過，之後在 Web 介面「系統設定」再填）===")
    for key, (label, *_rest) in AI_PROVIDERS.items():
        print(f"  {key}. {label}")
    choice = _ask("請選擇 AI 供應商，直接按 Enter 略過")
    if choice not in AI_PROVIDERS:
        print("  已略過 AI 設定。")
        return {}
    label, base_url, model, key_url = AI_PROVIDERS[choice]
    print(f"  {label} 的 API Key 可在這裡申請: {key_url}")
    api_key = getpass.getpass("請貼上 API Key（畫面不會顯示，按 Enter 略過）: ").strip()
    updates = {"OPENAI_BASE_URL": base_url, "OPENAI_MODEL_NAME": model}
    if api_key:
        updates["OPENAI_API_KEY"] = api_key
    return updates


def ensure_env_file() -> bool:
    """確保 .env 存在。回傳是否為這次新建立。"""
    # 後端啟動時可能已經建立過空白的 .env，這種情況一樣用範本補上
    if ENV_FILE.exists() and ENV_FILE.read_text(encoding="utf-8").strip():
        return False
    if ENV_EXAMPLE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
    else:
        ENV_FILE.touch()
    print(f"已建立設定檔: {ENV_FILE}")
    return True


def main() -> int:
    created = ensure_env_file()
    values = read_env()
    ask_credentials = needs_credentials(values)
    # 只在第一次設定時順便問 AI，之後都到 Web 介面修改
    ask_ai = (created or ask_credentials) and needs_ai_key(values)

    if not ask_credentials and not ask_ai:
        return 0

    if not sys.stdin.isatty():
        if ask_credentials:
            print(
                "尚未設定 WEB_USERNAME / WEB_PASSWORD，且目前無法互動輸入。\n"
                f"請編輯 {ENV_FILE} 填入後再啟動。"
            )
            return 1
        return 0

    try:
        updates: dict[str, str] = {}
        if ask_credentials:
            updates.update(prompt_credentials(values))
        if ask_ai:
            updates.update(prompt_ai(values))
    except (KeyboardInterrupt, EOFError):
        print("\n已取消設定。")
        return 1

    if updates:
        write_env(updates)
        print(f"\n設定已儲存到 {ENV_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
