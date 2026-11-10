"""
Playwright 瀏覽器：載入你的蝦皮登入狀態，開搜尋頁／商品頁，攔截頁面自己發出的 API 回應。

遇到蝦皮的人機驗證時不會試圖繞過：視窗可見的話會暫停，等你自己完成驗證再繼續。
"""
import asyncio
import json
import os
import random
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from . import shopee
from .errors import LoginRequiredError, RiskControlError

SEARCH_TIMEOUT_MS = 30_000
DETAIL_TIMEOUT_MS = 25_000


_BROWSER_MANAGED_HEADERS = {
    "accept", "accept-encoding", "authorization", "connection", "content-length",
    "content-type", "cookie", "host", "origin", "proxy-authorization", "referer",
    "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-user",
    "upgrade-insecure-requests", "user-agent",
}


def build_extra_headers(raw: Optional[dict]) -> dict:
    """擴充功能快照裡的標頭有些是瀏覽器自己會產生的，原樣套用會讓頁面空白，要濾掉。"""
    return {
        k: v for k, v in (raw or {}).items()
        if k and v is not None and k.lower() not in _BROWSER_MANAGED_HEADERS
    }


def build_context_options(snapshot: dict) -> dict:
    options = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1366, "height": 768},
        "locale": "zh-TW",
        "timezone_id": "Asia/Taipei",
        "color_scheme": "light",
    }
    env = snapshot.get("env") or {}
    headers = snapshot.get("headers") or {}
    navigator = env.get("navigator") or {}
    screen = env.get("screen") or {}
    ua = headers.get("User-Agent") or headers.get("user-agent") or navigator.get("userAgent")
    if ua:
        options["user_agent"] = ua
    language = (headers.get("Accept-Language") or headers.get("accept-language") or "").split(",")[0].strip()
    if language or navigator.get("language"):
        options["locale"] = language or navigator["language"]
    if (env.get("intl") or {}).get("timeZone"):
        options["timezone_id"] = env["intl"]["timeZone"]
    width, height = screen.get("width"), screen.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        options["viewport"] = {"width": int(width), "height": int(height)}
    extra = build_extra_headers(headers)
    if extra:
        options["extra_http_headers"] = extra
    return options


def persist_session_cookies(state_file: str, snapshot: dict, cookies: list) -> bool:
    """把瀏覽器最新的蝦皮 Cookie 寫回登入檔，通過驗證後新發的 Cookie 下次就能沿用。"""
    shopee_cookies = [c for c in cookies if "shopee" in str(c.get("domain", "")).lower()]
    if not shopee_cookies or not isinstance(snapshot, dict):
        return False
    updated = dict(snapshot)
    updated["cookies"] = shopee_cookies
    target = Path(state_file)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(tmp, target)
                return True
            except PermissionError:  # Windows 上檔案偶爾被其他程式短暫佔用
                if attempt == 9:
                    raise
                time.sleep(0.2)
    except OSError:
        return False
    return False


class ShopeeBrowser:
    def __init__(
        self,
        state_file: str,
        *,
        headless: bool,
        use_edge: bool = False,
        proxy: str = "",
        verify_timeout: int = 300,
        log: Callable[[str], None] = print,
    ):
        self.state_file = state_file
        self.headless = headless
        self.use_edge = use_edge
        self.proxy = proxy
        self.verify_timeout = verify_timeout
        self.log = log
        self._playwright = None
        self._browser = None
        self.context = None
        self.page = None
        self._snapshot: dict = {}
        self._session_ok = False

    async def __aenter__(self) -> "ShopeeBrowser":
        path = Path(self.state_file)
        if not path.exists():
            raise LoginRequiredError("找不到蝦皮登入狀態，請先貼上 Cookie。")
        self._snapshot = json.loads(path.read_text(encoding="utf-8"))
        enhanced = any(k in self._snapshot for k in ("env", "headers", "page", "storage"))
        storage_state = {"cookies": self._snapshot.get("cookies", [])} if enhanced else self._snapshot

        self._playwright = await async_playwright().start()
        launch = {"headless": self.headless, "channel": "msedge" if self.use_edge else "chrome"}
        if self.proxy:
            launch["proxy"] = {"server": self.proxy}
        try:
            self._browser = await self._playwright.chromium.launch(**launch)
        except Exception as exc:  # noqa: BLE001
            await self._playwright.stop()
            raise RuntimeError(
                "無法啟動瀏覽器，請確認電腦已安裝 Google Chrome（或在設定把 LOGIN_IS_EDGE 設為 true 改用 Edge）。"
                f"\n原始錯誤: {str(exc).splitlines()[0]}"
            ) from exc
        self.context = await self._browser.new_context(
            storage_state=storage_state, **build_context_options(self._snapshot)
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._session_ok and self.context:
                if persist_session_cookies(self.state_file, self._snapshot, await self.context.cookies()):
                    self.log("已把最新的蝦皮 Cookie 存回登入檔，下次執行會沿用。")
        except Exception as error:  # noqa: BLE001
            self.log(f"儲存最新 Cookie 時出錯: {error}")
        finally:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

    @staticmethod
    def _raise_if_blocked(url: str) -> None:
        if shopee.is_login_url(url):
            raise LoginRequiredError("登入狀態已失效，請重新登入蝦皮後再提取 Cookie。")
        if shopee.is_verify_url(url):
            raise RiskControlError(f"蝦皮要求人機驗證: {url}")

    async def _fetch(self, page, url: str, matcher, timeout_ms: int) -> dict:
        try:
            async with page.expect_response(matcher, timeout=timeout_ms) as info:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            response = await info.value
        except PlaywrightTimeoutError:
            self._raise_if_blocked(page.url)
            raise
        self._raise_if_blocked(page.url)
        if not response.ok:
            raise RuntimeError(f"蝦皮回應異常，狀態碼 {response.status}")
        payload = await response.json()
        if shopee.is_risk_blocked_payload(payload):
            raise RiskControlError(f"蝦皮風控攔截 (error={payload.get('error')})")
        return payload

    async def _wait_for_manual_verification(self, page) -> bool:
        self.log(
            f"蝦皮要求驗證。請在跳出的瀏覽器視窗完成驗證，完成後回到搜尋結果頁即可（最多等 {self.verify_timeout} 秒）。"
        )
        deadline = asyncio.get_running_loop().time() + self.verify_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                response = await page.wait_for_event(
                    "response", predicate=shopee.is_search_response, timeout=remaining * 1000
                )
            except PlaywrightTimeoutError:
                return False
            try:
                payload = await response.json()
            except Exception:  # noqa: BLE001
                continue
            if response.ok and not shopee.is_risk_blocked_payload(payload):
                self.log("偵測到驗證已完成，繼續執行。")
                return True

    async def search(self, url: str) -> dict:
        try:
            payload = await self._fetch(self.page, url, shopee.is_search_response, SEARCH_TIMEOUT_MS)
        except RiskControlError:
            if self.headless or self.verify_timeout <= 0:
                self.log("提示：把 RUN_HEADLESS 設為 false 後，遇到驗證時可以手動完成再繼續。")
                raise
            if not await self._wait_for_manual_verification(self.page):
                raise
            payload = await self._fetch(self.page, url, shopee.is_search_response, SEARCH_TIMEOUT_MS)
        self._session_ok = True
        return payload

    async def detail(self, url: str) -> Optional[dict]:
        """開商品頁並攔截詳情 API；拿不到回傳 None（呼叫端改用標題資料）。"""
        page = await self.context.new_page()
        try:
            return await self._fetch(page, url, shopee.is_detail_response, DETAIL_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            self.log("商品頁逾時，略過詳情。")
            return None
        finally:
            await page.close()

    @staticmethod
    async def pause(low: float, high: float) -> None:
        await asyncio.sleep(random.uniform(low, high))
