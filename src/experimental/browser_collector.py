"""Small, fail-closed, local browser experiment. Never an application provider.

Only the rendered viewport is inspected. No API requests, persistent sessions,
image downloads, credential automation, retries, scrolling or pagination.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import errno
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import stat
import sys
import tempfile
from threading import Thread
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

from src.domain.models.shopee import Product

SOURCE = "browser_experiment"
HOME_URL = "https://shopee.tw/"
ALLOWED_HOSTS = frozenset({"shopee.tw", "www.shopee.tw"})
CHANNELS = ("msedge", "chrome", "chromium")
RISK_NOTICE = (
    "實驗功能：蝦皮官方條款並沒有低頻率自動化的例外；慢速瀏覽仍可能違反條款，"
    "造成驗證、限制存取或帳號凍結。登入成功不代表獲准自動化存取。"
    "每批最多 5 筆，僅讀取目前可見內容；遇到阻擋即停止，不會重試或繞過。"
    "請先確認您有權進行此存取。"
)


class StopCode(str, Enum):
    COMPLETED = "completed"
    INVALID_REQUEST = "invalid_request"
    RISK_DECLINED = "risk_declined"
    CANCELLED = "cancelled"
    HTTP_BLOCKED = "http_blocked"
    AUTH_REQUIRED = "auth_required"
    VERIFICATION_REQUIRED = "verification_required"
    ACCESS_BLOCKED = "access_blocked"
    UNEXPECTED_ROUTE = "unexpected_route"
    MISSING_TITLE = "missing_title"
    AMBIGUOUS_TITLE = "ambiguous_title"
    MISSING_PRICE = "missing_price"
    AMBIGUOUS_PRICE = "ambiguous_price"
    DOM_LIMIT = "dom_limit"
    EMPTY_RESULTS = "empty_results"
    NAVIGATION_FAILED = "navigation_failed"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    OUTPUT_FAILED = "output_failed"
    OUTPUT_EXISTS = "output_exists"
    ALREADY_RUNNING = "already_running"
    LOCK_UNAVAILABLE = "lock_unavailable"
    REDIRECT_DETECTED = "redirect_detected"


MESSAGES = {
    StopCode.COMPLETED: "已完成本批可見商品讀取；資料仍屬實驗性、部分資料。",
    StopCode.INVALID_REQUEST: "請提供一個關鍵字或 1–5 個有效商品網址；間隔須為 60–300 秒，每批 1–5 筆。",
    StopCode.RISK_DECLINED: "未確認風險，未開始瀏覽。",
    StopCode.CANCELLED: "使用者已取消；保留已完成商品並關閉本次瀏覽器。",
    StopCode.HTTP_BLOCKED: "網站回傳 401、403 或 429；已停止，沒有重試。",
    StopCode.AUTH_REQUIRED: "偵測到登入要求；已停止，沒有自動登入或重試。",
    StopCode.VERIFICATION_REQUIRED: "偵測到驗證或 CAPTCHA；已停止，請勿以本工具繞過。",
    StopCode.ACCESS_BLOCKED: "偵測到存取限制或帳號異常；已停止，沒有重試。",
    StopCode.UNEXPECTED_ROUTE: "網址導向非預期網域或頁面；已停止。",
    StopCode.MISSING_TITLE: "找不到目前畫面可見的商品標題；已停止。",
    StopCode.AMBIGUOUS_TITLE: "目前畫面的商品標題不唯一；已停止。",
    StopCode.MISSING_PRICE: "找不到明示 NT$ 或 TWD 的可見單一價格；不會由 $ 推測幣別。",
    StopCode.AMBIGUOUS_PRICE: "可見價格有區間、多個金額或格式不明；已停止，不會猜價。",
    StopCode.DOM_LIMIT: "頁面內容超出保守檢查上限；已停止。",
    StopCode.EMPTY_RESULTS: "第一個搜尋畫面沒有可見的有效商品連結；未捲動或翻頁。",
    StopCode.NAVIGATION_FAILED: "瀏覽器導航或頁面讀取失敗；已停止，沒有重試。",
    StopCode.BROWSER_UNAVAILABLE: "無法啟動所選瀏覽器；請確認已安裝選用依賴及對應瀏覽器。",
    StopCode.OUTPUT_FAILED: "無法寫入結果檔案；請確認輸出目錄存在且可寫入。",
    StopCode.OUTPUT_EXISTS: "輸出路徑已存在；不會覆寫。請用 --output 指定新的檔名。",
    StopCode.ALREADY_RUNNING: "已有另一批瀏覽實驗執行中；本批未開啟瀏覽器，不允許平行瀏覽。",
    StopCode.LOCK_UNAVAILABLE: "無法安全取得本機單批執行鎖；未開啟瀏覽器。",
    StopCode.REDIRECT_DETECTED: "偵測到自動瀏覽的 HTTP 重新導向；已停止讀取。瀏覽器可能已發出重新導向請求。",
}


class CollectionStopped(Exception):
    def __init__(self, code: StopCode):
        self.code = code
        super().__init__(MESSAGES[code])


def _safe_url_parts(value: str):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("invalid URL")
    if any(ord(char) < 33 for char in value) or "\\" in value:
        raise ValueError("invalid URL")
    try:
        parts = urlsplit(value)
        # Checking netloc, not just hostname, also excludes every explicit port.
        if parts.scheme != "https" or parts.netloc.lower() not in ALLOWED_HOSTS:
            raise ValueError("invalid URL")
        if parts.username or parts.password or parts.port is not None:
            raise ValueError("invalid URL")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid URL") from exc
    return parts


def canonical_product_url(value: str) -> str:
    """Accept only public Shopee TW numeric item routes; discard all tracking."""
    parts = _safe_url_parts(value)
    path = unquote(parts.path)
    if "\\" in path or any(ord(char) < 32 for char in path):
        raise ValueError("invalid product URL")
    match = re.fullmatch(r"/product/([1-9][0-9]{0,19})/([1-9][0-9]{0,19})/?", path)
    if not match:
        match = re.fullmatch(r"/[^/]+-i\.([1-9][0-9]{0,19})\.([1-9][0-9]{0,19})/?", path)
    if not match:
        raise ValueError("invalid product URL")
    return f"https://shopee.tw/product/{match[1]}/{match[2]}"


@dataclass(frozen=True)
class CollectionRequest:
    keyword: str | None = None
    urls: tuple[str, ...] = ()
    max_items: int = 5
    interval_seconds: int = 60

    def __post_init__(self):
        if type(self.max_items) is not int or not 1 <= self.max_items <= 5:
            raise ValueError("invalid max_items")
        if type(self.interval_seconds) is not int or not 60 <= self.interval_seconds <= 300:
            raise ValueError("invalid interval_seconds")
        if self.keyword is not None:
            if not isinstance(self.keyword, str) or not self.keyword.strip() or len(self.keyword) > 200:
                raise ValueError("invalid keyword")
            if any(ord(char) < 32 for char in self.keyword) or self.urls:
                raise ValueError("choose keyword or urls")
            object.__setattr__(self, "keyword", self.keyword.strip())
        else:
            if not isinstance(self.urls, (tuple, list)) or not 1 <= len(self.urls) <= 5:
                raise ValueError("invalid URLs")
            urls = tuple(dict.fromkeys(canonical_product_url(url) for url in self.urls))
            object.__setattr__(self, "urls", urls)

    @classmethod
    def from_dict(cls, value: Any) -> "CollectionRequest":
        if not isinstance(value, dict) or set(value) - {"keyword", "urls", "max_items", "interval_seconds"}:
            raise ValueError("invalid request")
        if "urls" in value and not isinstance(value["urls"], list):
            raise ValueError("invalid URLs")
        keyword = value.get("keyword")
        if keyword is not None and not isinstance(keyword, str):
            raise ValueError("invalid keyword")
        if keyword and any(ord(char) < 32 for char in keyword):
            raise ValueError("invalid keyword")
        urls = value.get("urls", [])
        if bool(keyword and keyword.strip()) == bool(urls):
            raise ValueError("choose keyword or urls")
        normalized = dict(value, keyword=keyword.strip() if keyword and keyword.strip() else None, urls=urls)
        return cls(**normalized)

    @property
    def search_url(self) -> str:
        return "https://shopee.tw/search?" + urlencode({"keyword": self.keyword})


# This runs in the browser. Only small, visible fields and boolean safety flags
# leave it. No body text, HTML, cookies, network responses or hidden state leave.
VISIBLE_SNAPSHOT_JS = r"""({maxLinks}) => {
  const visible = (el) => {
    if (!(el instanceof Element)) return false;
    if (el.checkVisibility && !el.checkVisibility({checkOpacity:true, checkVisibilityCSS:true})) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.right <= 0 ||
        r.top >= innerHeight || r.left >= innerWidth) return false;
    for (let p = el; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.display === 'none' || s.visibility !== 'visible' || Number(s.opacity) === 0 || p.hidden)
        return false;
    }
    // Reject links/fields covered by a modal or clipped out of the viewport.
    // This is an inspection only, never a click or a scroll.
    if (document.elementFromPoint) {
      const x = (Math.max(0, r.left) + Math.min(innerWidth, r.right)) / 2;
      const y = (Math.max(0, r.top) + Math.min(innerHeight, r.bottom)) / 2;
      const hit = document.elementFromPoint(x, y);
      if (!hit || (hit !== el && !el.contains(hit))) return false;
    }
    return true;
  };
  const has = (selector) => Array.from(document.querySelectorAll(selector)).some(visible);
  const clean = (s) => s.replace(/\s+/g, ' ').trim();
  const visibleText = (node) => {
    const el = node.parentElement;
    if (!visible(el) || !document.createRange) return false;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) return false;
    // A visible ancestor is not evidence that this particular text is visible.
    // Require every text rectangle inside the viewport and unobscured. Partial
    // or split visible/offscreen fields fail closed rather than guessing.
    return rects.every(r => {
      if (r.top < 0 || r.left < 0 || r.bottom > innerHeight || r.right > innerWidth) return false;
      if (!document.elementFromPoint) return false;
      return document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2) === el;
    });
  };
  const headings = [];
  let headingLimit = false;
  for (const el of document.querySelectorAll('h1,[role="heading"][aria-level="1"]')) {
    if (!visible(el)) continue;
    const textWalker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const parts = [];
    let child, count = 0, complete = true;
    while ((child = textWalker.nextNode())) {
      if (++count > 500) { headingLimit = true; complete = false; break; }
      if (!clean(child.textContent || '')) continue;
      if (!visibleText(child)) { complete = false; break; }
      parts.push(child.textContent);
    }
    const title = clean(parts.join(''));
    if (complete && title) headings.push(title);
    if (title.length > 500 || headings.length > 10) { headingLimit = true; break; }
  }
  let verification = has('input[autocomplete="one-time-code"],iframe[src*="captcha" i],iframe[src*="challenge" i],[id*="captcha" i],[class*="captcha" i],[data-testid*="captcha" i]');
  let login = has('input[type="password"]') || headings.some(s => /^(登入|登錄|登录|log\s?in|sign\s?in)$/i.test(s));
  let blocked = false, limit = headingLimit;
  const prices = new Set();
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  let node, count = 0;
  while ((node = walker.nextNode())) {
    if (++count > 20000) { limit = true; break; }
    const el = node.parentElement;
    if (['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'].includes(el.tagName) || !visibleText(node)) continue;
    const raw = clean(node.textContent || '');
    if (!raw) continue;
    if (/captcha|人機驗證|機器人驗證|驗證碼|验证码|安全驗證|安全验证|驗證您的身分|驗證你的身份|verify.{0,20}(human|identity)|security verification/i.test(raw)) verification = true;
    if (/access denied|too many requests|unusual traffic|access restricted|temporarily blocked|account.{0,20}(frozen|suspended)|帳號.{0,15}(凍結|停權|異常)|訪問過於頻繁|存取遭拒|存取受限|操作过于频繁|操作過於頻繁/i.test(raw)) blocked = true;
    if (/(?:NT\$|TWD)/i.test(raw)) {
      // Never join a bare currency marker to parent/sibling text: that can
      // include offscreen amounts. A split currency/amount stays ambiguous.
      if (raw.length > 200) { limit = true; continue; }
      prices.add(raw);
      if (prices.size > 30) { limit = true; break; }
    }
  }
  const links = [];
  for (const el of document.querySelectorAll('a[href]')) {
    if (!visible(el)) continue;
    const href = el.href;
    if (/\/product\/[1-9][0-9]*\/[1-9][0-9]*(?:[/?#]|$)|-i\.[1-9][0-9]*\.[1-9][0-9]*(?:[/?#]|$)/.test(href)) {
      if (!links.includes(href)) links.push(href);
      if (links.length >= maxLinks) break;
    }
  }
  return {titles: headings.slice(0, 10), prices: Array.from(prices), links,
          verification, login, blocked, limit: limit || headings.length > 10};
}"""


def ensure_safe_snapshot(snapshot: dict, *, allow_login: bool = False) -> None:
    if snapshot.get("verification"):
        raise CollectionStopped(StopCode.VERIFICATION_REQUIRED)
    if snapshot.get("blocked"):
        raise CollectionStopped(StopCode.ACCESS_BLOCKED)
    if snapshot.get("login") and not allow_login:
        raise CollectionStopped(StopCode.AUTH_REQUIRED)
    if snapshot.get("limit"):
        raise CollectionStopped(StopCode.DOM_LIMIT)


PRICE_RE = re.compile(
    r"(?:(?:售價|價格|商品價格|price)\s*[:：]?\s*)?(?:NT\$|TWD)\s*"
    r"((?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)


def product_from_snapshot(snapshot: dict, url: str) -> dict:
    ensure_safe_snapshot(snapshot)
    titles = {" ".join(text.split()) for text in snapshot.get("titles", []) if isinstance(text, str) and text.strip()}
    if not titles:
        raise CollectionStopped(StopCode.MISSING_TITLE)
    if len(titles) != 1 or len(next(iter(titles))) > 500:
        raise CollectionStopped(StopCode.AMBIGUOUS_TITLE)
    candidates = snapshot.get("prices", [])
    if not candidates:
        raise CollectionStopped(StopCode.MISSING_PRICE)
    amounts = set()
    for text in candidates:
        match = PRICE_RE.fullmatch(text.strip()) if isinstance(text, str) else None
        if not match:
            raise CollectionStopped(StopCode.AMBIGUOUS_PRICE)
        try:
            amount = Decimal(match[1].replace(",", ""))
        except InvalidOperation:
            raise CollectionStopped(StopCode.AMBIGUOUS_PRICE) from None
        if not 0 <= amount <= 1_000_000_000:
            raise CollectionStopped(StopCode.AMBIGUOUS_PRICE)
        amounts.add(amount)
    if len(amounts) != 1:
        raise CollectionStopped(StopCode.AMBIGUOUS_PRICE)
    canonical = canonical_product_url(url)
    shop_id, item_id = canonical.rsplit("/", 2)[1:]
    return Product(
        product_id=f"{shop_id}.{item_id}", title=next(iter(titles)),
        price_twd=float(next(iter(amounts))), product_url=canonical,
        images=[], images_allowed=False, data_source=SOURCE, data_quality="partial",
    ).model_dump(mode="json")


@dataclass
class CollectionResult:
    products: list[dict] = field(default_factory=list)
    code: StopCode = StopCode.COMPLETED

    @property
    def exit_code(self) -> int:
        if self.code == StopCode.COMPLETED:
            return 0
        if self.code == StopCode.CANCELLED:
            return 130
        return 2

    def as_dict(self) -> dict:
        status = "completed" if self.code == StopCode.COMPLETED else "stopped"
        if self.code == StopCode.CANCELLED:
            status = "cancelled"
        return {
            "source": SOURCE,
            "products": self.products,
            "result": {"status": status, "code": self.code.value,
                       "message": MESSAGES[self.code], "collected_count": len(self.products)},
        }


class NavigationGuard:
    """Latch the first unsafe response/route. The latch is never reset/retried."""
    def __init__(self, page):
        self.page = page
        self.expected: str | None = None
        self.manual = True
        self.stop_code: StopCode | None = None

    def stop(self, code: StopCode):
        if self.stop_code is None:
            self.stop_code = code

    def check(self):
        if self.stop_code:
            raise CollectionStopped(self.stop_code)

    def allowed(self, url: str) -> bool:
        try:
            parts = _safe_url_parts(url)
            if self.manual:
                return True  # User-controlled same-site sign-in, before collection.
            expected = _safe_url_parts(self.expected or "")
            if expected.path == "/":
                return parts.path == "/" and not parts.fragment
            if expected.path == "/search":
                return parts.path == "/search" and not parts.fragment and parse_qs(parts.query) == parse_qs(expected.query)
            return canonical_product_url(url) == canonical_product_url(self.expected or "")
        except ValueError:
            return False

    def inspect_url(self):
        if not self.allowed(self.page.url):
            self.stop(self.denied_route_code(self.page.url))
        self.check()

    @staticmethod
    def denied_route_code(url: str) -> StopCode:
        try:
            path = _safe_url_parts(url).path.lower()
        except ValueError:
            return StopCode.UNEXPECTED_ROUTE
        if any(part in path for part in ("captcha", "verify", "verification", "challenge")):
            return StopCode.VERIFICATION_REQUIRED
        if any(part in path for part in ("login", "signin", "sign-in")):
            return StopCode.AUTH_REQUIRED
        return StopCode.UNEXPECTED_ROUTE

    def route(self, route):
        request = route.request
        if request.is_navigation_request() and request.frame is not self.page.main_frame and request.frame.parent_frame is None:
            self.stop(StopCode.UNEXPECTED_ROUTE)
            route.abort()
            return
        if request.is_navigation_request() and request.frame is self.page.main_frame:
            code = self.denied_route_code(request.url)
            if self.stop_code or code == StopCode.VERIFICATION_REQUIRED or not self.allowed(request.url):
                self.stop(code)
                route.abort()
                return
        if request.resource_type in {"image", "media"}:
            route.abort()  # Do not retrieve product images or media.
            return
        route.continue_()

    def response(self, response):
        request = response.request
        if request.is_navigation_request() and request.frame is self.page.main_frame:
            actual_url = getattr(response, "url", request.url)
            code = self.denied_route_code(actual_url)
            if code == StopCode.VERIFICATION_REQUIRED or not self.allowed(actual_url):
                self.stop(code)
            if 300 <= response.status < 400:
                # Playwright routes only the first request of a redirect chain.
                # The browser may already initiate the next hop before this
                # callback. Latch a stop before any extraction; do not claim
                # network-level redirect prevention or use a different client.
                location = response.header_value("location")
                destination = urljoin(actual_url, location) if location else actual_url
                code = self.denied_route_code(destination)
                if code == StopCode.VERIFICATION_REQUIRED or not self.allowed(destination):
                    self.stop(code)
                if not self.manual:
                    self.stop(StopCode.REDIRECT_DETECTED)
            self.inspect_redirect_chain(request)
        if response.status in {401, 403, 429}:
            try:
                _safe_url_parts(request.url)
            except ValueError:
                return
            # Inspect status only, including the site's own normal fetches.
            # Never inspect response bodies or make API calls ourselves.
            self.stop(StopCode.HTTP_BLOCKED)

    def inspect_redirect_chain(self, request):
        """Final-response ancestry is a second check against event races."""
        previous = getattr(request, "redirected_from", None)
        if previous is not None and not self.manual:
            self.stop(StopCode.REDIRECT_DETECTED)
        for _ in range(20):
            if previous is None:
                return
            code = self.denied_route_code(previous.url)
            if code == StopCode.VERIFICATION_REQUIRED or not self.allowed(previous.url):
                self.stop(code)
            previous = getattr(previous, "redirected_from", None)
        self.stop(StopCode.UNEXPECTED_ROUTE)


@contextmanager
def collector_lock(path: Path | None = None) -> Iterator[None]:
    """Per-user, cross-process OS lock; a crash releases it automatically.

    Keep the one-byte marker file in place: unlinking locked files permits
    inode races on POSIX. Never truncate, replace or delete an existing file.
    """
    if path is None:
        identity = hashlib.sha256(os.fsencode(str(Path.home()))).hexdigest()[:16]
        path = Path(tempfile.gettempdir()) / f"shopee-browser-collector-{identity}.lock"
    fd = None
    locked = False
    try:
        if path.is_symlink():
            raise CollectionStopped(StopCode.LOCK_UNAVAILABLE)
        flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = os.open(path, flags)
        else:
            os.write(fd, b"\0")
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != 1:
            raise CollectionStopped(StopCode.LOCK_UNAVAILABLE)
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise CollectionStopped(StopCode.LOCK_UNAVAILABLE)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            contended = exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(exc, "winerror", None) in {32, 33}
            code = StopCode.ALREADY_RUNNING if contended else StopCode.LOCK_UNAVAILABLE
            raise CollectionStopped(code) from None
        # Windows byte-range locks are mandatory: reading a byte held by a
        # different process fails before we can classify lock contention.
        # Acquire first, then verify the marker without modifying its data.
        if os.read(fd, 1) != b"\0":
            raise CollectionStopped(StopCode.LOCK_UNAVAILABLE)
    except OSError:
        raise CollectionStopped(StopCode.LOCK_UNAVAILABLE) from None
    else:
        yield
    finally:
        if fd is not None:
            try:
                if locked:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@contextmanager
def open_browser(channel: str) -> Iterator[Any]:
    """Create a fresh, visible browser. Nothing is persisted/exported."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CollectionStopped(StopCode.BROWSER_UNAVAILABLE) from None
    browser = context = None
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=False, channel=channel)
            context = browser.new_context(accept_downloads=False, service_workers="block")
            page = context.new_page()
            page.set_default_timeout(10000)
            page.set_default_navigation_timeout(30000)
        except Exception:
            if context:
                context.close()
            if browser:
                browser.close()
            raise CollectionStopped(StopCode.BROWSER_UNAVAILABLE) from None
        try:
            yield page
        finally:
            try:
                context.close()
            finally:
                browser.close()


def collect(
    request: CollectionRequest,
    *,
    channel: str,
    confirm_manual: Callable[[], bool],
    session_factory: Callable = open_browser,
    cancelled: Callable[[], bool] = lambda: False,
    lock_factory: Callable = collector_lock,
) -> CollectionResult:
    """One foreground batch. Exceptions are sanitized and earlier rows survive."""
    result = CollectionResult()

    def check_cancel():
        if cancelled():
            raise CollectionStopped(StopCode.CANCELLED)

    try:
        if channel not in CHANNELS:
            raise CollectionStopped(StopCode.INVALID_REQUEST)
        check_cancel()
        with lock_factory(), session_factory(channel) as page:
            guard = NavigationGuard(page)
            page.context.route("**/*", guard.route)
            page.on("response", guard.response)

            def read_snapshot(*, allow_login=False):
                check_cancel()
                guard.check()
                guard.inspect_url()
                if guard.denied_route_code(page.url) == StopCode.VERIFICATION_REQUIRED:
                    raise CollectionStopped(StopCode.VERIFICATION_REQUIRED)
                if not allow_login and re.search(r"/(?:buyer/)?(?:login|signin|sign-in)(?:/|$)", urlsplit(page.url).path, re.I):
                    raise CollectionStopped(StopCode.AUTH_REQUIRED)
                snapshot = page.evaluate(VISIBLE_SNAPSHOT_JS, {"maxLinks": request.max_items})
                ensure_safe_snapshot(snapshot, allow_login=allow_login)
                guard.check()
                return snapshot

            def navigate(url: str, *, readiness: str | None = None):
                check_cancel()
                guard.check()
                try:
                    response = page.goto(url, wait_until="load")
                except Exception:
                    guard.check()  # Preserve the route/HTTP block, not a raw error.
                    raise
                if response:
                    guard.response(response)
                if response and response.status in {401, 403, 429}:
                    guard.stop(StopCode.HTTP_BLOCKED)
                guard.check()
                snapshot = read_snapshot(allow_login=guard.manual)
                # A bounded render wait, not a navigation retry. Recheck safety
                # every 500 ms and never reload, scroll or fetch an API.
                for _ in range(10):
                    ready = readiness is None or (snapshot.get("links") if readiness == "search" else
                                                   snapshot.get("titles") and snapshot.get("prices"))
                    if ready:
                        break
                    page.wait_for_timeout(500)
                    snapshot = read_snapshot(allow_login=guard.manual)
                return snapshot

            def wait_between_pages():
                # Keep browser events active during the fixed delay, so a block
                # or cancellation can stop before the next navigation.
                for _ in range(request.interval_seconds):
                    check_cancel()
                    guard.check()
                    page.wait_for_timeout(1000)
                    guard.check()
                    read_snapshot(allow_login=guard.manual)
                read_snapshot(allow_login=guard.manual)

            def wait_for_manual_confirmation() -> bool:
                # Sync Playwright dispatches browser requests/events only on
                # its owning thread. Blocking that thread on input() would
                # stall the routed sign-in page, so only stdin runs elsewhere.
                # A daemon reader cannot delay CLI shutdown after a block or
                # Ctrl-C. No browser objects are passed to the reader.
                answers: Queue = Queue(maxsize=1)

                def read_terminal():
                    try:
                        answers.put((True, confirm_manual()))
                    except BaseException as exc:
                        answers.put((False, exc))

                Thread(target=read_terminal, daemon=True, name="browser-terminal-input").start()
                while True:
                    read_snapshot(allow_login=True)
                    try:
                        success, value = answers.get_nowait()
                    except Empty:
                        page.wait_for_timeout(100)
                        continue
                    if not success:
                        raise value
                    return bool(value)

            navigate(HOME_URL)
            if not wait_for_manual_confirmation():
                raise CollectionStopped(StopCode.CANCELLED)
            # Login is permitted only during the manual setup stage.
            read_snapshot(allow_login=False)
            guard.expected = page.url
            guard.manual = False
            guard.inspect_url()
            urls = list(request.urls[:request.max_items])
            if request.keyword is not None:
                wait_between_pages()
                guard.manual = False
                guard.expected = request.search_url
                snapshot = navigate(request.search_url, readiness="search")
                urls = []
                for link in snapshot.get("links", []):
                    try:
                        canonical = canonical_product_url(link)
                    except ValueError:
                        continue
                    if canonical not in urls:
                        urls.append(canonical)
                    if len(urls) >= request.max_items:
                        break
                if not urls:
                    raise CollectionStopped(StopCode.EMPTY_RESULTS)
            for url in urls:
                wait_between_pages()
                guard.manual = False
                guard.expected = url
                snapshot = navigate(url, readiness="product")
                result.products.append(product_from_snapshot(snapshot, url))
                check_cancel()
    except CollectionStopped as exc:
        result.code = exc.code
    except (KeyboardInterrupt, EOFError):
        result.code = StopCode.CANCELLED
    except Exception:
        result.code = StopCode.NAVIGATION_FAILED
    return result


def write_result(path: Path, result: CollectionResult) -> None:
    """Atomic local-only artifact; never emit browser state or raw exceptions."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".browser-result-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result.as_dict(), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        # A hard link atomically installs the complete file and refuses an
        # existing destination, including a symlink. Never replace user files.
        os.link(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def run_cli(argv: list[str] | None = None, *, input_fn=input, print_fn=print,
            session_factory: Callable = open_browser) -> int:
    parser = argparse.ArgumentParser(description="本機有視窗、一次性蝦皮瀏覽實驗（非授權搜尋服務）")
    parser.add_argument("--request", required=True, help="本機 JSON 檔案：keyword 或 urls、max_items、interval_seconds")
    parser.add_argument("--output", default="browser-results.json", help="本機 JSON 輸出路徑")
    parser.add_argument("--channel", choices=CHANNELS, default="msedge" if sys.platform == "win32" else "chromium")
    parser.add_argument("--risk-acknowledged", action="store_true", help="明確確認上述條款及帳號風險；不略過手動登入確認")
    args = parser.parse_args(argv)
    output_path = Path(args.output)
    if output_path.exists() or output_path.is_symlink():
        print_fn(MESSAGES[StopCode.OUTPUT_EXISTS])
        return 2
    if not output_path.parent.is_dir():
        print_fn(MESSAGES[StopCode.OUTPUT_FAILED])
        return 2
    try:
        request_path = Path(args.request)
        if request_path.stat().st_size > 32768:
            raise ValueError("request too large")
        request = CollectionRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8-sig")))
    except (OSError, UnicodeError, ValueError, TypeError):
        result = CollectionResult(code=StopCode.INVALID_REQUEST)
    else:
        print_fn(RISK_NOTICE)
        try:
            accepted = args.risk_acknowledged or input_fn("確認已了解風險並有權存取？輸入 yes 繼續：").strip().lower() == "yes"
            if not accepted:
                result = CollectionResult(code=StopCode.RISK_DECLINED)
            else:
                def confirm_manual():
                    print_fn("請在新開啟的瀏覽器手動登入。不要提供密碼或 Cookie 給本工具。"
                             "若看到驗證或封鎖，請取消，不要繼續本批。")
                    return input_fn("完成後輸入 yes 開始本批；其他輸入取消：").strip().lower() == "yes"
                result = collect(request, channel=args.channel, confirm_manual=confirm_manual,
                                 session_factory=session_factory)
        except (KeyboardInterrupt, EOFError):
            result = CollectionResult(code=StopCode.CANCELLED)
    try:
        write_result(output_path, result)
    except (OSError, ValueError):
        print_fn(MESSAGES[StopCode.OUTPUT_FAILED])
        return 2
    print_fn(f"{result.code.value}：{MESSAGES[result.code]} 已保存 {len(result.products)} 筆。")
    return result.exit_code
