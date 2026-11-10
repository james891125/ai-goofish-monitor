"""
蝦皮 (Shopee) 相關的 URL 組裝與 API 回應解析。

這裡只放純函式：不碰瀏覽器、不發請求，方便單元測試。
輸出欄位沿用原本管線使用的鍵名（商品標題 / 目前售價 / 商品連結 ...），
讓 AI 分析、通知、結果儲存與前端都不需要改動。
"""
import json
import os
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

SHOPEE_BASE_URL = (
    os.getenv("SHOPEE_BASE_URL", "https://shopee.tw").strip().rstrip("/")
    or "https://shopee.tw"
)

SEARCH_API_FRAGMENT = "/api/v4/search/search_items"
DETAIL_API_FRAGMENT = "/api/v4/pdp/get_pc"
SEARCH_PAGE_SIZE = 60

# 蝦皮 API 的金額是「實際金額 x 100000」的整數
PRICE_SCALE = 100000

LOGIN_URL_MARKERS = ("/buyer/login", "/account/login")
VERIFY_URL_MARKERS = ("/verify/captcha", "/verify/traffic", "/verify/bot")
# 被流量驗證攔下時 API 會回這個 error code
RISK_ERROR_CODES = {90309999}

def _image_host() -> str:
    """shopee.tw -> down-tw.img.susercontent.com"""
    region = SHOPEE_BASE_URL.rsplit(".", 1)[-1].lower()
    if not region.isalpha() or len(region) != 2:
        region = "tw"
    return f"https://down-{region}.img.susercontent.com/file"


def build_image_url(image_id: Any) -> str:
    if not image_id:
        return ""
    text = str(image_id)
    if text.startswith("http"):
        return text
    return f"{_image_host()}/{text}"


def build_item_url(shop_id: Any, item_id: Any) -> str:
    return f"{SHOPEE_BASE_URL}/product/{shop_id}/{item_id}"


def build_search_url(
    keyword: str,
    *,
    page: int = 0,
    min_price: Optional[str] = None,
    max_price: Optional[str] = None,
    sort_by_latest: bool = False,
) -> str:
    """組出搜尋頁網址。page 從 0 起算。"""
    params: dict[str, Any] = {"keyword": keyword, "page": max(0, int(page))}
    if min_price not in (None, ""):
        params["minPrice"] = str(min_price).strip()
    if max_price not in (None, ""):
        params["maxPrice"] = str(max_price).strip()
    if sort_by_latest:
        params["sortBy"] = "ctime"
        params["order"] = "desc"
    return f"{SHOPEE_BASE_URL}/search?{urlencode(params)}"


def wants_latest_sort(new_publish_option: Optional[str]) -> bool:
    """任務只要設了「新發布」相關選項，就改用最新上架排序。"""
    value = (new_publish_option or "").strip()
    return bool(value) and value != "__none__"


def is_login_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(marker in lowered for marker in LOGIN_URL_MARKERS)


def is_verify_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(marker in lowered for marker in VERIFY_URL_MARKERS)


def is_search_response(response: Any) -> bool:
    return SEARCH_API_FRAGMENT in getattr(response, "url", "")


def is_detail_response(response: Any) -> bool:
    return DETAIL_API_FRAGMENT in getattr(response, "url", "")


def is_risk_blocked_payload(payload: Any) -> bool:
    """API 回應是否代表被流量驗證 / 風控攔截。"""
    if not isinstance(payload, dict):
        return False
    return payload.get("error") in RISK_ERROR_CODES


def format_price(raw: Any) -> str:
    """把 API 的整數金額轉成顯示字串，例如 129000000 -> "$1,290"。"""
    if not isinstance(raw, (int, float)) or raw <= 0:
        return "價格異常"
    value = raw / PRICE_SCALE
    if abs(value - round(value)) < 1e-9:
        return f"${int(round(value)):,}"
    return f"${value:,.2f}"


def _format_price_range(low: Any, high: Any, single: Any) -> str:
    if (
        isinstance(low, (int, float))
        and isinstance(high, (int, float))
        and 0 < low < high
    ):
        return f"{format_price(low)} - {format_price(high)}"
    return format_price(single if single else low)


def _format_timestamp(ts: Any) -> str:
    if not isinstance(ts, (int, float)) or ts <= 0:
        return "未知時間"
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def format_join_duration(ctime: Any, now: Optional[datetime] = None) -> str:
    """賣場建立時間 (unix 秒) -> 「加入蝦皮 X 年 Y 個月」。"""
    if not isinstance(ctime, (int, float)) or ctime <= 0:
        return "未知"
    current = now or datetime.now()
    days = (current - datetime.fromtimestamp(int(ctime))).days
    if days < 30:
        return "加入蝦皮不足一個月"
    years, remainder = divmod(days, 365)
    months = min(11, remainder // 30)
    if years and months:
        return f"加入蝦皮 {years} 年 {months} 個月"
    if years:
        return f"加入蝦皮 {years} 年"
    return f"加入蝦皮 {months} 個月"


def _build_tags(basic: dict) -> list[str]:
    tags = []
    if basic.get("show_free_shipping"):
        tags.append("免運")
    if basic.get("is_official_shop"):
        tags.append("商城")
    if basic.get("shopee_verified"):
        tags.append("蝦皮優選")
    if basic.get("is_preferred_plus_seller"):
        tags.append("優選賣家+")
    if basic.get("is_adult"):
        tags.append("18+")
    discount = basic.get("discount")
    if discount:
        tags.append(f"折扣 {discount}")
    return tags


def _flatten_item_card(entry: dict) -> dict:
    """蝦皮較新的搜尋結果把資料拆在 item_card 的多個子區塊裡，攤平成舊格式的欄位。"""
    card = entry.get("item_card")
    if not isinstance(card, dict):
        return {}
    flat: dict[str, Any] = {}
    for block in card.values():
        if isinstance(block, dict):
            for key, value in block.items():
                flat.setdefault(key, value)
    for key, value in card.items():
        if not isinstance(value, dict):
            flat.setdefault(key, value)
    return flat


def describe_search_entry(payload: Any) -> str:
    """回傳第一筆搜尋結果的欄位結構（不含內容），解析不到標題時用來除錯。"""
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items or not isinstance(items[0], dict):
        return "回應中沒有 items"

    def shape(value: Any, depth: int = 0) -> Any:
        if isinstance(value, dict) and depth < 3:
            return {k: shape(v, depth + 1) for k, v in value.items()}
        return type(value).__name__

    return json.dumps(shape(items[0]), ensure_ascii=False)


def parse_search_items(payload: Any) -> list[dict]:
    """解析 search_items API，回傳商品基礎資訊列表。"""
    if not isinstance(payload, dict):
        return []
    results = []
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        basic = entry.get("item_basic") or _flatten_item_card(entry) or entry
        item_id = basic.get("itemid") or entry.get("itemid")
        shop_id = basic.get("shopid") or entry.get("shopid")
        if not item_id or not shop_id:
            continue

        images = [build_image_url(i) for i in (basic.get("images") or []) if i]
        main_image = build_image_url(basic.get("image")) or (images[0] if images else "")
        if main_image and not images:
            images = [main_image]

        rating = basic.get("item_rating") or {}
        rating_counts = rating.get("rating_count") or []
        before_discount = basic.get("price_before_discount")

        results.append(
            {
                "商品標題": basic.get("name") or "未知標題",
                "目前售價": _format_price_range(
                    basic.get("price_min"), basic.get("price_max"), basic.get("price")
                ),
                "商品原價": format_price(before_discount) if before_discount else "暫無",
                "“想要”人數": basic.get("liked_count", 0),
                "已售數量": basic.get("historical_sold", basic.get("sold", 0)),
                "庫存": basic.get("stock", "未知"),
                "商品評分": round(float(rating.get("rating_star") or 0), 2),
                "評價數量": rating_counts[0] if rating_counts else 0,
                "商品標籤": _build_tags(basic),
                "出貨地區": basic.get("shop_location") or "地區未知",
                "賣家暱稱": basic.get("shop_name") or f"shop_{shop_id}",
                "商品連結": build_item_url(shop_id, item_id),
                "釋出時間": _format_timestamp(basic.get("ctime")),
                "商品ID": str(item_id),
                "賣家ID": str(shop_id),
                "商品主圖連結": main_image,
                "商品圖片列表": images,
            }
        )
    return results


def _first(*values, default=None):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def _parse_attributes(item: dict) -> dict:
    attributes = {}
    for attr in item.get("attributes") or []:
        if isinstance(attr, dict) and attr.get("name") and attr.get("value"):
            attributes[str(attr["name"])] = str(attr["value"])
    return attributes


def _parse_variations(item: dict) -> list[dict]:
    variations = []
    for model in item.get("models") or []:
        if not isinstance(model, dict):
            continue
        variations.append(
            {
                "規格": model.get("name") or "",
                "價格": format_price(model.get("price")),
                "庫存": _first(model.get("stock"), model.get("normal_stock"), default=0),
            }
        )
    return variations


def parse_item_detail(payload: Any) -> dict:
    """解析商品詳情 API (pdp/get_pc)，回傳要合併進商品資訊的欄位。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    item = data.get("item") or {}
    review = data.get("product_review") or {}
    price_block = (data.get("product_price") or {}).get("price") or {}

    detail: dict[str, Any] = {}
    title = _first(item.get("title"), item.get("name"))
    if title:
        detail["商品標題"] = title
    description = _first(item.get("description"), data.get("description"))
    if description:
        detail["商品描述"] = str(description).strip()

    image_ids = _first(
        (data.get("product_images") or {}).get("images"), item.get("images"), default=[]
    )
    images = [build_image_url(i) for i in image_ids if i]
    if images:
        detail["商品圖片列表"] = images
        detail["商品主圖連結"] = images[0]

    single_price = _first(price_block.get("single_value"), item.get("price"))
    if isinstance(single_price, (int, float)) and single_price > 0:
        detail["目前售價"] = _format_price_range(
            _first(price_block.get("range_min"), item.get("price_min")),
            _first(price_block.get("range_max"), item.get("price_max")),
            single_price,
        )

    sold = _first(review.get("historical_sold"), item.get("historical_sold"))
    if sold is not None:
        detail["已售數量"] = sold
    liked = _first(review.get("liked_count"), item.get("liked_count"))
    if liked is not None:
        detail["“想要”人數"] = liked
    rating_star = _first(
        review.get("rating_star"), (item.get("item_rating") or {}).get("rating_star")
    )
    if rating_star is not None:
        detail["商品評分"] = round(float(rating_star), 2)
    total_rating = _first(review.get("total_rating_count"), review.get("cmt_count"))
    if total_rating is not None:
        detail["評價數量"] = total_rating
    stock = _first(item.get("stock"), item.get("normal_stock"))
    if stock is not None:
        detail["庫存"] = stock
    if item.get("brand"):
        detail["品牌"] = item["brand"]
    condition = item.get("condition")
    if condition in (1, 2):
        detail["商品狀況"] = "全新" if condition == 1 else "二手"

    attributes = _parse_attributes(item)
    if attributes:
        detail["商品屬性"] = attributes
    variations = _parse_variations(item)
    if variations:
        detail["規格列表"] = variations
    return detail


def parse_shop_info(payload: Any) -> dict:
    """從商品詳情 API 取出賣場資訊。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    shop = _first(data.get("shop_detailed"), data.get("shop"), default={})
    if not isinstance(shop, dict) or not shop:
        return {}
    account = shop.get("account") or {}
    info = {
        "賣家ID": str(_first(shop.get("shopid"), shop.get("shop_id"), default="")),
        "賣家暱稱": _first(shop.get("name"), account.get("username"), default="未知賣場"),
        "賣家帳號": account.get("username") or "",
        "賣場評分": round(float(shop.get("rating_star") or 0), 2),
        "賣場好評數": shop.get("rating_good", "未知"),
        "賣場中評數": shop.get("rating_normal", "未知"),
        "賣場差評數": shop.get("rating_bad", "未知"),
        "粉絲數": shop.get("follower_count", "未知"),
        "賣家在售商品數": shop.get("item_count", "未知"),
        "聊天回應率": (
            f"{shop['response_rate']}%" if shop.get("response_rate") is not None else "未知"
        ),
        "賣場所在地": _first(shop.get("shop_location"), shop.get("place"), default="未知"),
        "是否商城賣家": bool(shop.get("is_official_shop")),
        "是否蝦皮優選": bool(shop.get("is_shopee_verified")),
        "賣家註冊時長": format_join_duration(shop.get("ctime")),
    }
    return info


def matches_region(item: dict, region_filter: str) -> bool:
    """region 以「/」分段，任一段出現在出貨地即視為符合。"""
    parts = [p.strip() for p in (region_filter or "").split("/") if p.strip()]
    if not parts:
        return True
    # 蝦皮與使用者輸入可能混用「臺 / 台」，統一後再比對
    location = str(item.get("出貨地區") or "").replace("臺", "台")
    return any(part.replace("臺", "台") in location for part in parts)


def explain_filters(
    items: list[dict], *, free_shipping: bool = False, region_filter: str = ""
) -> str:
    """說明各篩選條件各會排除幾件商品，並列出實際的出貨地，方便判斷條件是否設太嚴。"""
    if not items:
        return ""
    lines = []
    if free_shipping:
        kept = sum(1 for i in items if "免運" in (i.get("商品標籤") or []))
        lines.append(f"免運篩選：{len(items)} 件中有 {kept} 件帶有免運標記")
    if region_filter:
        kept = sum(1 for i in items if matches_region(i, region_filter))
        locations: dict[str, int] = {}
        for item in items:
            name = str(item.get("出貨地區") or "未知")
            locations[name] = locations.get(name, 0) + 1
        top = "、".join(f"{k}×{v}" for k, v in sorted(locations.items(), key=lambda kv: -kv[1])[:8])
        lines.append(
            f"區域篩選「{region_filter}」：{len(items)} 件中有 {kept} 件符合；實際出貨地: {top}"
        )
    return "\n".join(lines)


def _normalize_for_match(text: str) -> str:
    """轉小寫並去掉空白與符號，讓「RTX 5070 Ti」與「rtx5070ti」視為相同。"""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def title_matches_keyword(title: str, keyword: str) -> bool:
    """標題是否包含搜尋關鍵字的每一個詞（不分順序、忽略空白與符號）。

    用來在花 token 之前先排除「搜尋結果裡的相關商品」，例如搜 5070ti 時的 5070、5060。
    標題解析不到時不排除，交給後續流程。
    """
    if not title or title == "未知標題":
        return True
    tokens = [_normalize_for_match(t) for t in str(keyword).split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return True
    normalized_title = _normalize_for_match(title)
    return all(token in normalized_title for token in tokens)


def filter_search_items(
    items: list[dict], *, free_shipping: bool = False, region_filter: str = ""
) -> list[dict]:
    filtered = []
    for item in items:
        if free_shipping and "免運" not in (item.get("商品標籤") or []):
            continue
        if not matches_region(item, region_filter):
            continue
        filtered.append(item)
    return filtered
