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
