"""
AI 請求訊息構造輔助函式
"""
from typing import Dict, List, Union


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
