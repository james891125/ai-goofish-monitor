import json

from PIL import Image

from src import ai_handler
from src.ai_message_builder import build_ai_product_payload


def _record():
    return {
        "爬取時間": "2026-01-01T00:00:00",
        "任務名稱": "t",
        "搜尋關鍵字": "rtx 5070ti",
        "商品資訊": {
            "商品標題": "RTX 5070 Ti",
            "目前售價": "$40,000",
            "商品描述": "字" * 2000,
            "商品圖片列表": ["https://img/" + "a" * 80] * 6,
            "商品主圖連結": "https://img/a",
            "商品連結": "https://shopee.tw/product/1/2",
        },
        "賣家資訊": {"卖场评分": 4.9},
        "價格參考": {
            "目前搜尋樣本": {"avg_price": 1},
            "歷史價格概覽": {"avg_price": 2},
            "本商品價格位置": {"market_avg_price": 3, "first_seen_at": "x", "deal_label": "高性價比"},
        },
        "price_insight": {"duplicate": True},
    }


def test_ai_payload_drops_urls_duplicates_and_truncates_description():
    text = build_ai_product_payload(_record())
    payload = json.loads(text)

    assert "\n" not in text
    assert "圖片" not in json.dumps(payload["商品資訊"], ensure_ascii=False)
    assert "price_insight" not in payload and "歷史價格概覽" not in payload["價格參考"]
    assert payload["價格參考"]["本商品價格位置"] == {"market_avg_price": 3, "deal_label": "高性價比"}
    assert len(payload["商品資訊"]["商品描述"]) < 700
    assert len(text) < len(json.dumps(_record(), ensure_ascii=False, indent=2)) / 3


def test_images_are_resized_before_encoding(tmp_path, monkeypatch):
    path = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000), "red").save(path)
    monkeypatch.setattr(ai_handler, "AI_IMAGE_MAX_SIDE", 512)

    import base64
    from io import BytesIO

    encoded = ai_handler.encode_image_to_base64(str(path))
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert max(image.size) == 512 and image.format == "JPEG"
