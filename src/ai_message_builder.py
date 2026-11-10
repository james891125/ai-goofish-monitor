"""
AI 請求訊息構造輔助函式
"""
import json
from typing import Any, Dict, List, Union

DESCRIPTION_MAX_CHARS = 600
# 圖片網址很長又對判斷沒有幫助，圖片本身另外以圖片訊息送出
_ITEM_FIELDS_DROPPED = {"商品圖片列表", "商品主圖連結", "商品連結", "賣家ID", "發布時間"}
_PRICE_POSITION_FIELDS = (
    "current_price",
    "market_avg_price",
    "market_median_price",
    "price_change_percent",
    "deal_score",
    "deal_label",
)


TEXT_ONLY_ANALYSIS_NOTE = (
    "補充說明：本次未提供商品圖片，請僅根據商品文字欄位和賣家資訊判斷，不要推斷圖片內容。"
)


def build_analysis_text_prompt(
    product_json: str,
    prompt_text: str,
    *,
    include_images: bool,
) -> str:
    note = "" if include_images else f"\n{TEXT_ONLY_ANALYSIS_NOTE}\n"
    value_note = (
        "\n如果商品 JSON 中包含“價格參考”或 price_insight，請結合價格位置、歷史走勢、"
        "配置、成色、附件、賣家資訊綜合判斷價效比。"
        "你可以額外輸出可選欄位 value_score(0-100) 和 value_summary，"
        "但必須保留原有 is_recommended/reason 等欄位。\n"
    )
    return f"""請基於你的專業知識和我的要求，分析以下完整的商品JSON資料：

```json
{product_json}
```

    {prompt_text}
    {value_note}
    {note}"""


def build_user_message_content(
    text_prompt: str,
    image_data_urls: List[str],
) -> Union[str, List[Dict[str, object]]]:
    if not image_data_urls:
        return text_prompt

    user_content: List[Dict[str, object]] = [
        {"type": "image_url", "image_url": {"url": url}}
        for url in image_data_urls
    ]
    user_content.append({"type": "text", "text": text_prompt})
    return user_content


def build_ai_product_payload(product_data: Dict[str, Any]) -> str:
    """只保留 AI 判斷需要的欄位並壓縮成單行 JSON，減少每次請求的 token。"""
    item = dict(product_data.get("商品資訊") or {})
    for key in _ITEM_FIELDS_DROPPED:
        item.pop(key, None)
    description = item.get("商品描述")
    if isinstance(description, str) and len(description) > DESCRIPTION_MAX_CHARS:
        item["商品描述"] = description[:DESCRIPTION_MAX_CHARS] + "…（已截斷）"

    reference = product_data.get("價格參考") or {}
    position = reference.get("本商品價格位置") or {}
    slim_reference = {
        "目前搜尋樣本": reference.get("目前搜尋樣本"),
        "本商品價格位置": {k: position[k] for k in _PRICE_POSITION_FIELDS if k in position},
    }
    payload = {
        "搜尋關鍵字": product_data.get("搜尋關鍵字"),
        "商品資訊": item,
        "賣家資訊": product_data.get("賣家資訊") or {},
        "價格參考": slim_reference,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
