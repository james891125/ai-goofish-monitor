import asyncio
import json
import os
import tempfile
from datetime import datetime
from typing import Optional

from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from src.ai_handler import (
    download_all_images,
    get_ai_analysis,
    send_notification,
    cleanup_task_images,
)
from src.config import (
    AI_DEBUG_MODE,
    LOGIN_IS_EDGE,
    RUN_HEADLESS,
    RUNNING_IN_DOCKER,
    SKIP_AI_ANALYSIS,
    STATE_FILE,
)
from src.shopee import (
    build_search_url,
    explain_filters,
    filter_search_items,
    is_detail_response,
    is_login_url,
    is_risk_blocked_payload,
    is_search_response,
    is_verify_url,
    parse_item_detail,
    parse_search_items,
    parse_shop_info,
    wants_latest_sort,
)
from src.utils import (
    get_link_unique_key,
    log_time,
    random_sleep,
    save_to_jsonl,
)
from src.rotation import RotationPool, load_state_files, parse_proxy_pool, RotationItem
from src.failure_guard import FailureGuard
from src.services.account_strategy_service import resolve_account_runtime_plan
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.item_analysis_dispatcher import (
    ItemAnalysisDispatcher,
    ItemAnalysisJob,
)
from src.services.price_history_service import (
    build_market_reference,
    load_price_snapshots,
    record_market_snapshots,
)
from src.services.result_storage_service import load_processed_link_keys


class RiskControlError(Exception):
    pass


class LoginRequiredError(Exception):
    """Raised when Shopee redirects to the login page."""


FAILURE_GUARD = FailureGuard()
EDGE_DOCKER_WARNING_PRINTED = False


SEARCH_RESPONSE_TIMEOUT_MS = 30_000
DETAIL_RESPONSE_TIMEOUT_MS = 25_000
# 視窗可見時，遇到蝦皮驗證最多等使用者幾秒（0 表示不等待）
MANUAL_VERIFY_TIMEOUT_SECONDS = max(0, int(os.getenv("MANUAL_VERIFY_TIMEOUT_SECONDS", "300") or 0))


def _resolve_browser_channel() -> str:
    global EDGE_DOCKER_WARNING_PRINTED
    if RUNNING_IN_DOCKER:
        if LOGIN_IS_EDGE and not EDGE_DOCKER_WARNING_PRINTED:
            print(
                "檢測到 LOGIN_IS_EDGE=true，但 Docker 映象未內建 Edge，"
                "任務執行時將改用 Chromium。"
            )
            EDGE_DOCKER_WARNING_PRINTED = True
        return "chromium"
    return "msedge" if LOGIN_IS_EDGE else "chrome"


def _should_analyze_images(task_config: dict) -> bool:
    raw_value = task_config.get("analyze_images", True)
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() not in {"false", "0", "no", "off"}


CHROMIUM_CRASH_DUMPS_DIRNAME = "chromium-crashpad"


def build_chromium_launch_args(crash_dumps_dir: str) -> list[str]:
    """Chromium 啟動參數。

    Docker 裡的 Playwright Chromium 會拉起 chrome_crashpad_handler。資料庫路徑一旦落到
    ``/``，handler 會自監控重啟並佔住大量記憶體。這裡禁用 crash reporter，同時把 dump
    目錄固定到可寫臨時目錄。
    """
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-web-security",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-features=IsolateOrigins,site-per-process,Crashpad",
        f"--crash-dumps-dir={crash_dumps_dir}",
    ]


def prepare_chromium_launch_args() -> list[str]:
    crash_dumps_dir = os.path.join(tempfile.gettempdir(), CHROMIUM_CRASH_DUMPS_DIRNAME)
    os.makedirs(crash_dumps_dir, exist_ok=True)
    return build_chromium_launch_args(crash_dumps_dir)


def _format_failure_reason(reason: str, limit: int = 500) -> str:
    if not reason:
        return "未知錯誤"
    cleaned = " ".join(str(reason).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


async def _notify_task_failure(
    task_config: dict, reason: str, *, cookie_path: Optional[str]
) -> None:
    task_name = task_config.get("task_name", "未命名任務")
    keyword = task_config.get("keyword", "")
    formatted_reason = _format_failure_reason(reason)

    # Some failures are deterministic misconfiguration and should pause/notify immediately.
    pause_immediately = any(
        marker in formatted_reason
        for marker in (
            "未找到可用的代理地址",
            "未找到可用的登入狀態檔案",
        )
    )

    guard_result = FAILURE_GUARD.record_failure(
        task_name,
        formatted_reason,
        cookie_path=cookie_path,
        min_failures_to_pause=1 if pause_immediately else None,
    )

    if not guard_result.get("should_notify"):
        print(
            f"[FailureGuard] 任務 '{task_name}' 失敗計數 {guard_result.get('consecutive_failures')}/{FAILURE_GUARD.threshold}，暫不通知。"
        )
        return

    paused_until = guard_result.get("paused_until")
    paused_until_str = (
        paused_until.strftime("%Y-%m-%d %H:%M:%S") if paused_until else "N/A"
    )

    product_data = {
        "商品標題": f"[任務異常] {task_name}",
        "目前售價": "N/A",
        "商品連結": "#",
    }
    notify_reason = (
        f"任務執行失敗(已連續 {guard_result.get('consecutive_failures')}/{FAILURE_GUARD.threshold} 次): {formatted_reason}"
        f"\n任務: {task_name}"
        f"\n關鍵詞: {keyword or 'N/A'}"
        f"\n已自動暫停重試，暫停到: {paused_until_str}"
        f"\n修復後(更新登入態/cookies檔案)將自動恢復。"
    )

    try:
        await send_notification(product_data, notify_reason)
    except Exception as e:
        print(f"傳送任務異常通知失敗: {e}")


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_rotation_settings(task_config: dict) -> dict:
    account_cfg = task_config.get("account_rotation") or {}
    proxy_cfg = task_config.get("proxy_rotation") or {}

    account_enabled = _as_bool(
        account_cfg.get("enabled"),
        _as_bool(os.getenv("ACCOUNT_ROTATION_ENABLED"), False),
    )
    account_mode = (
        account_cfg.get("mode") or os.getenv("ACCOUNT_ROTATION_MODE", "per_task")
    ).lower()
    account_state_dir = account_cfg.get("state_dir") or os.getenv(
        "ACCOUNT_STATE_DIR", "state"
    )
    account_retry_limit = _as_int(
        account_cfg.get("retry_limit"),
        _as_int(os.getenv("ACCOUNT_ROTATION_RETRY_LIMIT"), 2),
    )
    account_blacklist_ttl = _as_int(
        account_cfg.get("blacklist_ttl_sec"),
        _as_int(os.getenv("ACCOUNT_BLACKLIST_TTL"), 300),
    )

    proxy_enabled = _as_bool(
        proxy_cfg.get("enabled"), _as_bool(os.getenv("PROXY_ROTATION_ENABLED"), False)
    )
    proxy_mode = (
        proxy_cfg.get("mode") or os.getenv("PROXY_ROTATION_MODE", "per_task")
    ).lower()
    proxy_pool = proxy_cfg.get("proxy_pool") or os.getenv("PROXY_POOL", "")
    proxy_retry_limit = _as_int(
        proxy_cfg.get("retry_limit"),
        _as_int(os.getenv("PROXY_ROTATION_RETRY_LIMIT"), 2),
    )
    proxy_blacklist_ttl = _as_int(
        proxy_cfg.get("blacklist_ttl_sec"),
        _as_int(os.getenv("PROXY_BLACKLIST_TTL"), 300),
    )

    return {
        "account_enabled": account_enabled,
        "account_mode": account_mode,
        "account_state_dir": account_state_dir,
        "account_retry_limit": max(1, account_retry_limit),
        "account_blacklist_ttl": max(0, account_blacklist_ttl),
        "proxy_enabled": proxy_enabled,
        "proxy_mode": proxy_mode,
        "proxy_pool": proxy_pool,
        "proxy_retry_limit": max(1, proxy_retry_limit),
        "proxy_blacklist_ttl": max(0, proxy_blacklist_ttl),
    }


def _get_ai_analysis_concurrency(task_config: dict) -> int:
    configured = task_config.get("ai_analysis_concurrency")
    default = _as_int(os.getenv("AI_ANALYSIS_CONCURRENCY"), 2)
    return max(1, _as_int(configured, default))


def _default_context_options() -> dict:
    return {
        # 蝦皮桌面版網頁；若登入狀態快照帶有環境資訊，會被快照覆蓋。
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "locale": "zh-TW",
        "timezone_id": "Asia/Taipei",
        "color_scheme": "light",
    }


def _clean_kwargs(options: dict) -> dict:
    return {k: v for k, v in options.items() if v is not None}


def _looks_like_mobile(ua: str) -> Optional[bool]:
    if not ua:
        return None
    ua_lower = ua.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return True
    if "windows" in ua_lower or "macintosh" in ua_lower:
        return False
    return None


def _build_context_overrides(snapshot: dict) -> dict:
    env = snapshot.get("env") or {}
    headers = snapshot.get("headers") or {}
    navigator = env.get("navigator") or {}
    screen = env.get("screen") or {}
    intl = env.get("intl") or {}

    overrides = {}

    ua = (
        headers.get("User-Agent")
        or headers.get("user-agent")
        or navigator.get("userAgent")
    )
    if ua:
        overrides["user_agent"] = ua

    accept_language = headers.get("Accept-Language") or headers.get("accept-language")
    locale = None
    if accept_language:
        locale = accept_language.split(",")[0].strip()
    elif navigator.get("language"):
        locale = navigator["language"]
    if locale:
        overrides["locale"] = locale

    tz = intl.get("timeZone")
    if tz:
        overrides["timezone_id"] = tz

    width = screen.get("width")
    height = screen.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        overrides["viewport"] = {"width": int(width), "height": int(height)}

    dpr = screen.get("devicePixelRatio")
    if isinstance(dpr, (int, float)):
        overrides["device_scale_factor"] = float(dpr)

    touch_points = navigator.get("maxTouchPoints")
    if isinstance(touch_points, (int, float)):
        overrides["has_touch"] = touch_points > 0

    mobile_flag = _looks_like_mobile(ua or "")
    if mobile_flag is not None:
        overrides["is_mobile"] = mobile_flag

    return _clean_kwargs(overrides)


# 這些頭由瀏覽器按請求型別生成。擴充功能快照裡常見的是某次 XHR 的值
# （Sec-Fetch-Dest: empty / Sec-Fetch-Mode: cors / Accept: */*）。
# 如果原樣套到 BrowserContext，文件和腳本請求會被改成 CORS 空請求，搜尋頁只剩白屏。
_BROWSER_MANAGED_EXTRA_HEADERS = {
    "accept",
    "accept-encoding",
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "origin",
    "proxy-authorization",
    "referer",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "upgrade-insecure-requests",
    "user-agent",
}


def _build_extra_headers(raw_headers: Optional[dict]) -> dict:
    if not raw_headers:
        return {}
    headers = {}
    for key, value in raw_headers.items():
        if not key or key.lower() in _BROWSER_MANAGED_EXTRA_HEADERS or value is None:
            continue
        headers[key] = value
    return headers


def _raise_if_blocked(url: str) -> None:
    if is_login_url(url):
        raise LoginRequiredError(
            f"Login required: redirected to {url} (cookies/state likely expired)"
        )
    if is_verify_url(url):
        raise RiskControlError(f"蝦皮要求人機驗證: {url}")


async def _fetch_search_payload(page, search_url: str) -> dict:
    """開啟搜尋頁，並攔截頁面自己發出的 search_items API 回應。"""
    try:
        async with page.expect_response(
            is_search_response, timeout=SEARCH_RESPONSE_TIMEOUT_MS
        ) as response_info:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        response = await response_info.value
    except PlaywrightTimeoutError:
        _raise_if_blocked(page.url)
        raise
    _raise_if_blocked(page.url)
    if not response.ok:
        raise RuntimeError(f"蝦皮搜尋 API 回應異常，狀態碼: {response.status}")
    payload = await response.json()
    if is_risk_blocked_payload(payload):
        raise RiskControlError(f"蝦皮搜尋 API 被風控攔截 (error={payload.get('error')})")
    return payload


async def _wait_for_manual_verification(page, timeout_seconds: int) -> bool:
    """瀏覽器視窗可見時，讓使用者自己完成蝦皮的驗證；完成後頁面會重新拿到正常的搜尋結果。"""
    print(
        "\n==================== 需要手動驗證 ====================\n"
        "蝦皮要求驗證。請在剛開啟的瀏覽器視窗中完成驗證（必要時重新登入），\n"
        f"完成後回到搜尋結果頁即可。最多等待 {timeout_seconds} 秒。\n"
        "======================================================"
    )
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        try:
            response = await page.wait_for_event(
                "response",
                predicate=is_search_response,
                timeout=remaining * 1000,
            )
        except PlaywrightTimeoutError:
            return False
        try:
            payload = await response.json()
        except Exception:
            continue
        if response.ok and not is_risk_blocked_payload(payload):
            log_time("偵測到驗證已完成，繼續執行。")
            return True


async def _load_search_page(page, search_url: str) -> dict:
    try:
        return await _fetch_search_payload(page, search_url)
    except RiskControlError:
        if RUN_HEADLESS or MANUAL_VERIFY_TIMEOUT_SECONDS <= 0:
            print("提示：在 .env 設定 RUN_HEADLESS=false 後，遇到驗證時可以手動完成再繼續。")
            raise
        if not await _wait_for_manual_verification(page, MANUAL_VERIFY_TIMEOUT_SECONDS):
            raise
        return await _fetch_search_payload(page, search_url)


async def _load_item_detail(context, item_url: str) -> Optional[dict]:
    """開啟商品頁並攔截詳情 API。拿不到時回傳 None，由呼叫端退回使用搜尋結果資料。"""
    detail_page = await context.new_page()
    try:
        async with detail_page.expect_response(
            is_detail_response, timeout=DETAIL_RESPONSE_TIMEOUT_MS
        ) as detail_info:
            await detail_page.goto(
                item_url, wait_until="domcontentloaded", timeout=DETAIL_RESPONSE_TIMEOUT_MS
            )
        response = await detail_info.value
        if not response.ok:
            print(f"   錯誤: 商品詳情 API 回應失敗，狀態碼: {response.status}")
            return None
        payload = await response.json()
        if is_risk_blocked_payload(payload):
            raise RiskControlError(
                f"蝦皮商品詳情 API 被風控攔截 (error={payload.get('error')})"
            )
        return payload
    except PlaywrightTimeoutError:
        _raise_if_blocked(detail_page.url)
        print("   錯誤: 開啟商品詳情頁或等待 API 回應逾時。")
        return None
    finally:
        await detail_page.close()


async def scrape_shopee(task_config: dict, debug_limit: int = 0):
    """
    【核心執行器】
    根據單個任務配置，非同步爬取蝦皮商品資料，並對每個新發現的商品進行即時的、獨立的AI分析和通知。
    """
    keyword = task_config["keyword"]
    max_pages = task_config.get("max_pages", 1)
    personal_only = task_config.get("personal_only", False)
    min_price = task_config.get("min_price")
    max_price = task_config.get("max_price")
    ai_prompt_text = task_config.get("ai_prompt_text", "")
    analyze_images = _should_analyze_images(task_config)
    decision_mode = str(task_config.get("decision_mode", "ai")).strip().lower()
    if decision_mode not in {"ai", "keyword"}:
        decision_mode = "ai"
    keyword_rules = task_config.get("keyword_rules") or []
    free_shipping = task_config.get("free_shipping", False)
    raw_new_publish = task_config.get("new_publish_option") or ""
    new_publish_option = raw_new_publish.strip()
    if new_publish_option == "__none__":
        new_publish_option = ""
    region_filter = (task_config.get("region") or "").strip()

    processed_links = set()
    history_run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    history_seen_item_ids: set[str] = set()
    historical_snapshots = load_price_snapshots(keyword)
    result_filename = build_result_filename(keyword)
    processed_links = load_processed_link_keys(keyword)
    if processed_links:
        print(f"LOG: 發現已存在結果集 {result_filename}，已載入 {len(processed_links)} 個歷史商品用於去重。")
    else:
        print(f"LOG: 結果集 {result_filename} 目前為空，將寫入新記錄。")

    rotation_settings = _get_rotation_settings(task_config)
    account_items = load_state_files(rotation_settings["account_state_dir"])
    runtime_plan = resolve_account_runtime_plan(
        strategy=task_config.get("account_strategy"),
        account_state_file=task_config.get("account_state_file"),
        has_root_state_file=os.path.exists(STATE_FILE),
        available_account_files=account_items,
    )
    forced_account = runtime_plan["forced_account"]
    if runtime_plan["prefer_root_state"]:
        account_items = [STATE_FILE]
        rotation_settings["account_enabled"] = False
    elif runtime_plan["use_account_pool"]:
        rotation_settings["account_enabled"] = True
    else:
        rotation_settings["account_enabled"] = False

    account_pool = RotationPool(
        account_items, rotation_settings["account_blacklist_ttl"], "account"
    )
    proxy_pool = RotationPool(
        parse_proxy_pool(rotation_settings["proxy_pool"]),
        rotation_settings["proxy_blacklist_ttl"],
        "proxy",
    )

    selected_account: Optional[RotationItem] = None
    selected_proxy: Optional[RotationItem] = None

    def _select_account(force_new: bool = False) -> Optional[RotationItem]:
        nonlocal selected_account
        if forced_account:
            return RotationItem(value=forced_account)
        if not rotation_settings["account_enabled"]:
            if os.path.exists(STATE_FILE):
                return RotationItem(value=STATE_FILE)
            return None
        if (
            rotation_settings["account_mode"] == "per_task"
            and selected_account
            and not force_new
        ):
            return selected_account
        picked = account_pool.pick_random()
        return picked or selected_account

    def _select_proxy(force_new: bool = False) -> Optional[RotationItem]:
        nonlocal selected_proxy
        if not rotation_settings["proxy_enabled"]:
            return None
        if (
            rotation_settings["proxy_mode"] == "per_task"
            and selected_proxy
            and not force_new
        ):
            return selected_proxy
        picked = proxy_pool.pick_random()
        return picked or selected_proxy

    async def _run_scrape_attempt(state_file: str, proxy_server: Optional[str]) -> int:
        processed_item_count = 0
        stop_scraping = False

        if not os.path.exists(state_file):
            raise FileNotFoundError(f"登入狀態檔案不存在: {state_file}")

        snapshot_data = None
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                snapshot_data = json.load(f)
        except Exception as e:
            print(f"警告：讀取登入狀態檔案失敗，將直接按路徑使用: {e}")

        async with async_playwright() as p:
            launch_args = prepare_chromium_launch_args()

            launch_kwargs = {"headless": RUN_HEADLESS, "args": launch_args}
            if proxy_server:
                launch_kwargs["proxy"] = {"server": proxy_server}

            launch_kwargs["channel"] = _resolve_browser_channel()

            browser = await p.chromium.launch(**launch_kwargs)

            context_kwargs = _default_context_options()
            storage_state_arg = state_file
            analysis_dispatcher: Optional[ItemAnalysisDispatcher] = None

            if isinstance(snapshot_data, dict):
                # 新版擴充功能匯出的增強快照，包含環境和Header
                if any(
                    key in snapshot_data
                    for key in ("env", "headers", "page", "storage")
                ):
                    print(f"檢測到增強瀏覽器快照，應用環境參數: {state_file}")
                    storage_state_arg = {"cookies": snapshot_data.get("cookies", [])}
                    context_kwargs.update(_build_context_overrides(snapshot_data))
                    extra_headers = _build_extra_headers(snapshot_data.get("headers"))
                    if extra_headers:
                        context_kwargs["extra_http_headers"] = extra_headers
                else:
                    storage_state_arg = snapshot_data

            context_kwargs = _clean_kwargs(context_kwargs)
            context = await browser.new_context(
                storage_state=storage_state_arg, **context_kwargs
            )
            # 賣場資訊直接來自商品詳情 API，不需要另外開賣場頁面
            shop_infos: dict[str, dict] = {}

            async def _load_shop_info(shop_id: str) -> dict:
                return shop_infos.get(str(shop_id), {})

            analysis_dispatcher = ItemAnalysisDispatcher(
                concurrency=_get_ai_analysis_concurrency(task_config),
                skip_ai_analysis=SKIP_AI_ANALYSIS,
                seller_loader=_load_shop_info,
                image_downloader=download_all_images,
                ai_analyzer=get_ai_analysis,
                notifier=send_notification,
                saver=save_to_jsonl,
            )

            page = await context.new_page()

            try:
                sort_by_latest = wants_latest_sort(new_publish_option)
                if personal_only:
                    log_time("蝦皮沒有「個人閒置」篩選，已忽略 personal_only。")

                for page_num in range(1, max_pages + 1):
                    if stop_scraping:
                        break
                    search_url = build_search_url(
                        keyword,
                        page=page_num - 1,
                        min_price=min_price,
                        max_price=max_price,
                        sort_by_latest=sort_by_latest,
                    )
                    log_time(f"開始處理第 {page_num}/{max_pages} 頁: {search_url}")
                    search_payload = await _load_search_page(page, search_url)
                    raw_items = parse_search_items(search_payload)
                    if not raw_items:
                        log_time(f"第 {page_num} 頁沒有商品，停止翻頁。")
                        if AI_DEBUG_MODE:
                            print(json.dumps(search_payload, ensure_ascii=False)[:2000])
                        break

                    basic_items = filter_search_items(
                        raw_items,
                        free_shipping=bool(free_shipping),
                        region_filter=region_filter,
                    )
                    log_time(
                        f"第 {page_num} 頁解析到 {len(raw_items)} 件商品，"
                        f"篩選後剩 {len(basic_items)} 件。"
                    )
                    if not basic_items:
                        print(
                            explain_filters(
                                raw_items,
                                free_shipping=bool(free_shipping),
                                region_filter=region_filter,
                            )
                            or "沒有設定免運或區域篩選，但商品仍被排除，請回報此日誌。"
                        )
                    historical_snapshots.extend(
                        record_market_snapshots(
                            keyword=keyword,
                            task_name=task_config.get("task_name", "Untitled Task"),
                            items=basic_items,
                            run_id=history_run_id,
                            snapshot_time=datetime.now().isoformat(),
                            seen_item_ids=history_seen_item_ids,
                        )
                    )

                    total_items_on_page = len(basic_items)
                    for i, item_data in enumerate(basic_items, 1):
                        if debug_limit > 0 and processed_item_count >= debug_limit:
                            log_time(f"已達到除錯上限 ({debug_limit})，停止取得新商品。")
                            stop_scraping = True
                            break

                        unique_key = get_link_unique_key(item_data["商品連結"])
                        if unique_key in processed_links:
                            log_time(
                                f"[頁內進度 {i}/{total_items_on_page}] 商品 '{item_data['商品標題'][:20]}...' 已存在，跳過。"
                            )
                            continue

                        log_time(
                            f"[頁內進度 {i}/{total_items_on_page}] 發現新商品，取得詳情: {item_data['商品標題'][:30]}..."
                        )
                        await random_sleep(2, 4)

                        shop_id = item_data.get("賣家ID")
                        detail_payload = await _load_item_detail(
                            context, item_data["商品連結"]
                        )
                        if detail_payload:
                            item_data.update(parse_item_detail(detail_payload))
                            shop_info = parse_shop_info(detail_payload)
                            if shop_info:
                                shop_infos[str(shop_id)] = shop_info
                                item_data["賣家暱稱"] = shop_info["賣家暱稱"]
                        else:
                            log_time("未取得商品詳情，改用搜尋結果中的基本資料。")

                        final_record = {
                            "爬取時間": datetime.now().isoformat(),
                            "搜尋關鍵字": keyword,
                            "任務名稱": task_config.get("task_name", "Untitled Task"),
                            "商品資訊": item_data,
                            "賣家資訊": {},
                        }
                        price_reference = build_market_reference(
                            keyword=keyword,
                            item=item_data,
                            current_market_items=basic_items,
                            historical_snapshots=historical_snapshots,
                        )
                        final_record["價格參考"] = price_reference
                        final_record["price_insight"] = price_reference.get(
                            "本商品價格位置", {}
                        )

                        analysis_dispatcher.submit(
                            ItemAnalysisJob(
                                keyword=keyword,
                                task_name=task_config.get("task_name", "Untitled Task"),
                                decision_mode=decision_mode,
                                analyze_images=analyze_images,
                                prompt_text=ai_prompt_text,
                                keyword_rules=tuple(keyword_rules or []),
                                final_record=final_record,
                                seller_id=str(shop_id) if shop_id else None,
                                registration_duration_text=shop_infos.get(
                                    str(shop_id), {}
                                ).get("賣家註冊時長", "未知"),
                            )
                        )

                        processed_links.add(unique_key)
                        processed_item_count += 1
                        log_time(
                            f"商品已提交背景分析。累計處理 {processed_item_count} 個新商品。"
                        )
                        # 放慢節奏，避免對蝦皮造成過多請求
                        await random_sleep(5, 10)

                    if not stop_scraping and page_num < max_pages:
                        print(f"--- 第 {page_num} 頁處理完畢，稍作休息後翻頁... ---")
                        await random_sleep(10, 15)

            except PlaywrightTimeoutError as e:
                if is_login_url(page.url):
                    raise LoginRequiredError(
                        f"Login required: redirected to {page.url} (cookies/state likely expired)"
                    ) from e
                print(f"\n操作超時錯誤: 頁面元素或網路響應未在規定時間內出現。\n{e}")
                raise
            except asyncio.CancelledError:
                log_time("收到取消訊號，正在終止目前爬蟲任務...")
                raise
            except Exception as e:
                if type(e).__name__ == "TargetClosedError":
                    log_time("瀏覽器已關閉，忽略後續異常（可能是任務被停止）。")
                    return processed_item_count
                print(f"\n爬取過程中發生未知錯誤: {e}")
                raise
            finally:
                if analysis_dispatcher is not None:
                    log_time("等待後臺分析任務完成...")
                    await analysis_dispatcher.join()
                log_time("任務執行完畢，瀏覽器將在5秒後自動關閉...")
                await asyncio.sleep(5)
                if debug_limit:
                    input("按回車鍵關閉瀏覽器...")
                await browser.close()

        return processed_item_count

    processed_item_count = 0
    attempt_limit = max(
        rotation_settings["account_retry_limit"],
        rotation_settings["proxy_retry_limit"],
        1,
    )
    last_error = ""
    last_state_path: Optional[str] = None

    # If this task is already in a paused state, skip immediately.
    task_name_for_guard = task_config.get("task_name", "未命名任務")
    pause_cookie_path = None
    if (
        isinstance(task_config.get("account_state_file"), str)
        and task_config.get("account_state_file").strip()
    ):
        pause_cookie_path = task_config.get("account_state_file").strip()
    elif os.path.exists(STATE_FILE):
        pause_cookie_path = STATE_FILE

    decision = FAILURE_GUARD.should_skip_start(
        task_name_for_guard, cookie_path=pause_cookie_path
    )
    if decision.skip:
        print(
            f"[FailureGuard] 任務 '{task_name_for_guard}' 已暫停重試 (連續失敗 {decision.consecutive_failures}/{FAILURE_GUARD.threshold})"
        )
        if decision.should_notify:
            try:
                await send_notification(
                    {
                        "商品標題": f"[任務暫停] {task_name_for_guard}",
                        "目前售價": "N/A",
                        "商品連結": "#",
                    },
                    "任務處於暫停狀態，將跳過執行。\n"
                    f"原因: {decision.reason}\n"
                    f"連續失敗: {decision.consecutive_failures}/{FAILURE_GUARD.threshold}\n"
                    f"暫停到: {decision.paused_until.strftime('%Y-%m-%d %H:%M:%S') if decision.paused_until else 'N/A'}\n"
                    "修復方法: 更新登入態/cookies檔案後會自動恢復。",
                )
            except Exception as e:
                print(f"傳送任務暫停通知失敗: {e}")

        cleanup_task_images(task_config.get("task_name", "default"))
        return 0

    for attempt in range(1, attempt_limit + 1):
        if attempt == 1:
            selected_account = _select_account()
            selected_proxy = _select_proxy()
        else:
            if (
                rotation_settings["account_enabled"]
                and rotation_settings["account_mode"] == "on_failure"
            ):
                account_pool.mark_bad(selected_account, last_error)
                selected_account = _select_account(force_new=True)
            if (
                rotation_settings["proxy_enabled"]
                and rotation_settings["proxy_mode"] == "on_failure"
            ):
                proxy_pool.mark_bad(selected_proxy, last_error)
                selected_proxy = _select_proxy(force_new=True)

        if rotation_settings["account_enabled"] and not selected_account:
            last_error = "未找到可用的登入狀態檔案，無法繼續執行任務。"
            print(last_error)
            break
        if not rotation_settings["account_enabled"] and not selected_account:
            last_error = "未找到可用的登入狀態檔案，無法繼續執行任務。"
            print(last_error)
            break
        if rotation_settings["proxy_enabled"] and not selected_proxy:
            last_error = "未找到可用的代理地址，無法繼續執行任務。"
            print(last_error)
            break

        state_path = selected_account.value if selected_account else STATE_FILE
        last_state_path = state_path
        proxy_server = selected_proxy.value if selected_proxy else None
        if rotation_settings["account_enabled"]:
            print(f"帳號輪換：使用登入狀態 {state_path}")
        if rotation_settings["proxy_enabled"] and proxy_server:
            print(f"IP 輪換：使用代理 {proxy_server}")

        try:
            processed_item_count += await _run_scrape_attempt(state_path, proxy_server)
            last_error = ""
            FAILURE_GUARD.record_success(task_name_for_guard)
            break
        except LoginRequiredError as e:
            last_error = str(e)
            print(f"檢測到登入失效/重定向: {e}")
            break
        except RiskControlError as e:
            last_error = str(e)
            print(f"檢測到風控或驗證觸發: {e}")
            # 風控驗證通常不是簡單輪換能解決的，避免無意義重試。
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            print(f"本次嘗試失敗: {last_error}")
            if attempt < attempt_limit:
                print("將嘗試輪換帳號/IP 後重試...")

    if last_error:
        await _notify_task_failure(task_config, last_error, cookie_path=last_state_path)

    # 清理任務圖片目錄
    cleanup_task_images(task_config.get("task_name", "default"))

    return processed_item_count
