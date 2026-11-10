import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from src import shopee
from src.services.price_history_service import parse_price_value

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_build_search_url_includes_filters():
    url = shopee.build_search_url(
        "macbook air", page=1, min_price="5000", max_price="20000", sort_by_latest=True
    )
    assert url.startswith(f"{shopee.SHOPEE_BASE_URL}/search?")
    assert "keyword=macbook+air" in url
    assert "page=1" in url
    assert "minPrice=5000" in url and "maxPrice=20000" in url
    assert "sortBy=ctime" in url and "order=desc" in url


def test_build_search_url_omits_empty_filters():
    url = shopee.build_search_url("switch")
    assert "minPrice" not in url and "sortBy" not in url and "page=0" in url


def test_wants_latest_sort():
    assert shopee.wants_latest_sort("最新") is True
    assert shopee.wants_latest_sort("__none__") is False
    assert shopee.wants_latest_sort(None) is False


def test_parse_search_items_maps_pipeline_fields():
    items = shopee.parse_search_items(_load("shopee_search.json"))
    assert len(items) == 2  # 缺少 ID 的專案被略過

    first = items[0]
    assert first["商品ID"] == "111" and first["賣家ID"] == "222"
    assert first["商品連結"] == f"{shopee.SHOPEE_BASE_URL}/product/222/111"
    assert first["目前售價"] == "$18,500"
    assert first["商品原價"] == "$20,000"
    assert first["已售數量"] == 12
    assert first["商品評分"] == 4.88 and first["評價數量"] == 30
    assert first["出貨地區"] == "臺北市大安區"
    assert "免運" in first["商品標籤"] and "蝦皮優選" in first["商品標籤"]
    assert len(first["商品圖片列表"]) == 2
    assert first["商品主圖連結"].endswith("/file/tw-aaa")

    second = items[1]
    assert second["目前售價"] == "$30,000 - $45,500"
    assert second["商品圖片列表"] == [second["商品主圖連結"]]


def test_parse_search_items_handles_bad_payload():
    assert shopee.parse_search_items(None) == []
    assert shopee.parse_search_items({"items": None}) == []


def test_price_strings_are_parseable_by_price_history():
    assert parse_price_value("$18,500") == 18500.0
    assert parse_price_value("$30,000 - $45,500") == 30000.0
    assert parse_price_value("¥1,200") == 1200.0
    assert parse_price_value("價格異常") is None


def test_parse_item_detail_and_shop_info():
    payload = _load("shopee_detail.json")
    detail = shopee.parse_item_detail(payload)
    assert detail["商品標題"].endswith("電池健康 92%")
    assert detail["商品描述"] == "自用機，無維修紀錄，附原廠充電器。"
    assert len(detail["商品圖片列表"]) == 3
    assert detail["目前售價"] == "$18,500"
    assert detail["已售數量"] == 13 and detail["“想要”人數"] == 46
    assert detail["商品狀況"] == "二手" and detail["品牌"] == "Apple"
    assert detail["商品屬性"] == {"保固": "無"}
    assert detail["規格列表"] == [{"規格": "太空灰", "價格": "$18,500", "庫存": 2}]

    shop = shopee.parse_shop_info(payload)
    assert shop["賣家暱稱"] == "阿明的3C小舖" and shop["賣家ID"] == "222"
    assert shop["聊天回應率"] == "98%" and shop["粉絲數"] == 1234
    assert shop["賣家註冊時長"].startswith("加入蝦皮")


def test_parse_detail_handles_missing_data():
    assert shopee.parse_item_detail({"error": 90309999}) == {}
    assert shopee.parse_shop_info({"data": {}}) == {}


def test_filter_search_items_by_shipping_and_region():
    items = shopee.parse_search_items(_load("shopee_search.json"))
    assert [i["商品ID"] for i in shopee.filter_search_items(items, free_shipping=True)] == ["111"]
    assert [i["商品ID"] for i in shopee.filter_search_items(items, region_filter="高雄市")] == ["333"]
    assert len(shopee.filter_search_items(items, region_filter="臺北市/高雄市")) == 2
    assert len(shopee.filter_search_items(items)) == 2


def test_url_and_payload_detection():
    assert shopee.is_login_url("https://shopee.tw/buyer/login?next=x")
    assert shopee.is_verify_url("https://shopee.tw/verify/captcha?anti_bot=1")
    assert not shopee.is_login_url("https://shopee.tw/search?keyword=a")
    assert shopee.is_risk_blocked_payload({"error": 90309999})
    assert not shopee.is_risk_blocked_payload({"error": None, "items": []})
    assert shopee.is_search_response(
        SimpleNamespace(url="https://shopee.tw/api/v4/search/search_items?keyword=a")
    )
    assert shopee.is_detail_response(
        SimpleNamespace(url="https://shopee.tw/api/v4/pdp/get_pc?item_id=1")
    )


def test_format_join_duration():
    now = datetime(2026, 1, 1)
    two_years_ago = datetime(2023, 10, 1).timestamp()
    assert shopee.format_join_duration(two_years_ago, now) == "加入蝦皮 2 年 3 個月"
    assert shopee.format_join_duration(datetime(2025, 12, 20).timestamp(), now) == "加入蝦皮不足一個月"
    assert shopee.format_join_duration(None) == "未知"


def test_explain_filters_reports_why_items_were_dropped():
    items = shopee.parse_search_items(_load("shopee_search.json"))
    text = shopee.explain_filters(items, free_shipping=True, region_filter="Taipei")
    assert "1 件帶有免運標記" in text
    assert "0 件符合" in text and "北市大安區" in text
    assert shopee.explain_filters([], free_shipping=True) == ""


def test_parse_search_items_supports_item_card_layout():
    payload = {
        "items": [
            {
                "item_card": {
                    "itemid": 5,
                    "shopid": 6,
                    "item_card_displayed_asset": {"name": "卡片版商品", "image": "tw-card"},
                    "item_card_display_price": {"price": 1290000000},
                }
            }
        ]
    }

    items = shopee.parse_search_items(payload)

    assert items[0]["商品標題"] == "卡片版商品"
    assert items[0]["目前售價"] == "$12,900"
    assert items[0]["商品主圖連結"].endswith("/tw-card")
    shape = shopee.describe_search_entry(payload)
    assert "item_card_displayed_asset" in shape and "卡片版商品" not in shape


def test_title_matches_keyword_ignores_spaces_and_order_but_keeps_model_digits():
    kw = "rtx 5070ti"
    assert shopee.title_matches_keyword("ZOTAC RTX5070 Ti 天啟 OC 顯示卡", kw)
    assert shopee.title_matches_keyword("微星 GeForce RTX 5070 TI 16G", kw)
    assert not shopee.title_matches_keyword("MSI 微星 RTX5070 12G 顯示卡", kw)
    assert not shopee.title_matches_keyword("華碩 RTX 5060 Ti 16G", kw)
    # 解析不到標題時不排除
    assert shopee.title_matches_keyword("未知標題", kw)
    assert shopee.title_matches_keyword("任何商品", "")


def test_parse_search_items_supports_current_asset_layout():
    payload = {
        "items": [
            {
                "item_basic": None,
                "itemid": 7,
                "shopid": 8,
                "item_card_displayed_asset": {
                    "name": "Apple Mac mini M4 16G/256G",
                    "image": "tw-img",
                    "images": ["tw-img", "tw-img2"],
                    "shop_location": "高雄市",
                    "display_price": {"price": 2290000000, "strikethrough_price": 2490000000},
                    "discount_tag": {"discount_text": "8%"},
                    "promotion_label_list": [{"text": "滿額免運"}],
                },
                "item_data": {
                    "itemid": 7,
                    "shopid": 8,
                    "item_card_display_price": {"price": 2290000000, "strikethrough_price": 2490000000},
                    "item_card_display_sold_count": {"historical_sold_count": 15},
                    "liked_count": 30,
                    "ctime": 1700000000,
                    "is_sold_out": False,
                    "shop_data": {"shop_name": "某某3C"},
                    "item_rating": {"rating_star": 4.9, "rating_count": [20, 0, 0, 0, 1, 19]},
                    "shopee_verified": True,
                },
            }
        ]
    }

    item = shopee.parse_search_items(payload)[0]

    assert item["商品標題"] == "Apple Mac mini M4 16G/256G"
    assert item["目前售價"] == "$22,900" and item["商品原價"] == "$24,900"
    assert item["出貨地區"] == "高雄市" and item["賣家暱稱"] == "某某3C"
    assert item["已售數量"] == 15 and item["評價數量"] == 20
    assert "免運" in item["商品標籤"] and item["已售完"] is False
    assert len(item["商品圖片列表"]) == 2


def test_detail_price_uses_range_when_variations_have_no_single_price():
    payload = {
        "data": {
            "item": {"title": "多規格"},
            "product_price": {"price": {"range_min": 1000000000, "range_max": 2000000000}},
        }
    }

    assert shopee.parse_item_detail(payload)["目前售價"] == "$10,000 - $20,000"
