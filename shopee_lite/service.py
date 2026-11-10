"""命令列與網頁介面共用的流程：讀設定、執行搜尋、寫出 CSV、傳 Webhook、儲存登入狀態。"""
import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

from . import envfile
from .ai import PROVIDERS, AIClient
from .browser import ShopeeBrowser
from .exporter import build_csv, send_csv_webhook
from .login_state import LoginStateError, normalize_login_state, summarize_login_state
from .runner import RunOptions, RunResult, run_search

STATE_FILE = Path(os.getenv("SHOPEE_STATE_FILE", "state/shopee.json"))
OUTPUT_DIR = Path(os.getenv("SHOPEE_OUTPUT_DIR", "output"))


def load_env() -> dict[str, str]:
    load_dotenv(envfile.ENV_PATH, override=True)
    return envfile.read_env()


def _flag(values: dict, key: str, default: bool) -> bool:
    raw = values.get(key, os.getenv(key))
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    api_key: str
    base_url: str
    model: str
    webhook_url: str
    proxy: str
    headless: bool
    use_edge: bool
    verify_timeout: int

    def ai_client(self) -> AIClient:
        return AIClient(self.base_url, self.api_key, self.model, self.proxy)


def load_settings() -> Settings:
    values = load_env()

    def get(key: str, default: str = "") -> str:
        return (values.get(key) or os.getenv(key) or default).strip()

    default_provider = PROVIDERS["gemini"]
    return Settings(
        api_key=get("OPENAI_API_KEY"),
        base_url=get("OPENAI_BASE_URL", default_provider[1]),
        model=get("OPENAI_MODEL_NAME", default_provider[2]),
        webhook_url=get("WEBHOOK_URL"),
        proxy=get("PROXY_URL"),
        headless=_flag(values, "RUN_HEADLESS", False),
        use_edge=_flag(values, "LOGIN_IS_EDGE", False),
        verify_timeout=int(get("MANUAL_VERIFY_TIMEOUT_SECONDS", "300") or 0),
    )


def save_login(content: str) -> dict:
    """驗證並儲存貼上的蝦皮登入狀態；格式不對時丟出 LoginStateError。"""
    state = normalize_login_state(content)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return login_status()


def login_status() -> dict:
    if not STATE_FILE.exists():
        return {"saved": False, "logged_in": False}
    try:
        summary = summarize_login_state(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {"saved": True, "logged_in": False, "invalid": True}
    return {"saved": True, **summary}


def _safe_name(text: str) -> str:
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")[:40] or "result"


def output_path(keywords: list[str]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{_safe_name('_'.join(keywords))}_{stamp}.csv"


async def run_job(
    options: RunOptions,
    *,
    log: Callable[[str], None] = print,
    should_stop: Optional[Callable[[], bool]] = None,
    settings: Optional[Settings] = None,
    browser=None,
) -> tuple[Path, RunResult]:
    """執行一次搜尋並寫出 CSV。browser 可注入（測試用），預設開真的瀏覽器。"""
    settings = settings or load_settings()
    options.validate()
    ai_client = settings.ai_client() if options.ai != "off" else None

    async def work(active_browser) -> RunResult:
        return await run_search(options, active_browser, ai_client, log, should_stop)

    if browser is not None:
        result = await work(browser)
    else:
        async with ShopeeBrowser(
            str(STATE_FILE),
            headless=settings.headless,
            use_edge=settings.use_edge,
            proxy=settings.proxy,
            verify_timeout=settings.verify_timeout,
            log=log,
        ) as real_browser:
            result = await work(real_browser)

    path = output_path(options.keywords)
    path.write_bytes(build_csv(result.rows, result.mode))
    log(f"完成：{len(result.rows)} 件商品，已存成 {path}")
    for line in result.summary:
        log(line)
    return path, result


def send_webhook(path: Path, settings: Optional[Settings] = None) -> str:
    settings = settings or load_settings()
    if not settings.webhook_url:
        raise ValueError("尚未設定 Webhook 網址（WEBHOOK_URL）。")
    return send_csv_webhook(
        settings.webhook_url,
        path.read_bytes(),
        path.name,
        f"蝦皮商品清單：{path.stem}",
        settings.proxy,
    )


def run_blocking(options: RunOptions, **kwargs) -> tuple[Path, RunResult]:
    return asyncio.run(run_job(options, **kwargs))
