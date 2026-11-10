"""
蝦皮登入狀態（Cookie）整理與檢查。

使用者貼上的內容可能是：
1. chrome-extension 匯出的快照（含 cookies / env / headers）
2. Playwright storage_state（{"cookies": [...], "origins": [...]}）
3. 其他 Cookie 擴充功能匯出的純 Cookie 陣列

這裡統一整理成爬蟲可以直接載入的格式，並回報是否真的帶有蝦皮登入資訊。
"""
import json
from datetime import datetime
from typing import Any, Optional

# 蝦皮登入後才會有內容的 Cookie
LOGIN_COOKIE_NAMES = ("SPC_EC", "SPC_ST")
USER_ID_COOKIE_NAME = "SPC_U"
_EMPTY_COOKIE_VALUES = {"", "-", '""'}
_SAME_SITE_MAP = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
}


class LoginStateError(ValueError):
    """貼上的內容無法當作蝦皮登入狀態使用。"""


def _is_shopee_cookie(cookie: dict) -> bool:
    return "shopee" in str(cookie.get("domain") or "").lower()


def _normalize_cookie(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    cookie = {
        "name": str(raw["name"]),
        "value": str(raw.get("value") or ""),
        "domain": str(raw.get("domain") or ""),
        "path": str(raw.get("path") or "/"),
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", False)),
        "sameSite": _SAME_SITE_MAP.get(str(raw.get("sameSite") or "").lower(), "Lax"),
    }
    expires = raw.get("expires", raw.get("expirationDate"))
    if isinstance(expires, (int, float)) and expires > 0:
        cookie["expires"] = float(expires)
    return cookie


def normalize_login_state(content: str) -> dict:
    """解析貼上的文字並整理成可儲存的登入狀態，格式不對時丟出 LoginStateError。"""
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LoginStateError("貼上的內容不是有效的 JSON，請重新從擴充功能複製。") from exc

    if isinstance(parsed, list):
        parsed = {"cookies": parsed}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("cookies"), list):
        raise LoginStateError("內容裡找不到 cookies，請確認是用擴充功能「提取登入狀態」複製的內容。")

    cookies = [c for c in (_normalize_cookie(raw) for raw in parsed["cookies"]) if c]
    if not any(_is_shopee_cookie(cookie) for cookie in cookies):
        raise LoginStateError("內容裡沒有蝦皮的 Cookie，請先開啟並登入 shopee.tw 再提取。")

    state = dict(parsed)
    state["cookies"] = cookies
    state.setdefault("origins", [])
    return state


def summarize_login_state(state: Any) -> dict:
    """回傳登入狀態摘要，不包含任何 Cookie 內容。"""
    cookies = state.get("cookies") if isinstance(state, dict) else None
    cookies = [c for c in cookies or [] if isinstance(c, dict)]
    shopee_cookies = [c for c in cookies if _is_shopee_cookie(c)]
    by_name = {str(c.get("name")): c for c in shopee_cookies}

    login_cookies = [
        by_name[name]
        for name in LOGIN_COOKIE_NAMES
        if name in by_name
        and str(by_name[name].get("value") or "").strip() not in _EMPTY_COOKIE_VALUES
    ]
    expiries = [
        c["expires"]
        for c in login_cookies
        if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0
    ]
    expires_at = min(expiries) if expiries else None
    user_id = str((by_name.get(USER_ID_COOKIE_NAME) or {}).get("value") or "").strip()

    return {
        "cookie_count": len(shopee_cookies),
        "logged_in": bool(login_cookies),
        "shopee_user_id": user_id if user_id not in _EMPTY_COOKIE_VALUES else "",
        "expires_at": (
            datetime.fromtimestamp(expires_at).isoformat(timespec="seconds")
            if expires_at
            else None
        ),
        "expired": bool(expires_at and expires_at < datetime.now().timestamp()),
    }
