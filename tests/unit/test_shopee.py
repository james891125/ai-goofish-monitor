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
    assert len(items) == 2  # 缺少 ID 的項目被略過

    first = items[0]
    assert first["商品ID"] == "111" and first["卖家ID"] == "222"
    assert first["商品链接"] == f"{shopee.SHOPEE_BASE_URL}/product/222/111"
    assert first["当前售价"] == "$18,500"
    assert first["商品原价"] == "$20,000"
    assert first["已售数量"] == 12
    assert first["商品评分"] == 4.88 and first["评价数量"] == 30
    assert first["发货地区"] == "台北市大安區"
    assert "免運" in first["商品标签"] and "蝦皮優選" in first["商品标签"]
    assert len(first["商品图片列表"]) == 2
    assert first["商品主图链接"].endswith("/file/tw-aaa")

    second = items[1]
    assert second["当前售价"] == "$30,000 - $45,500"
    assert second["商品图片列表"] == [second["商品主图链接"]]


def test_parse_search_items_handles_bad_payload():
    assert shopee.parse_search_items(None) == []
    assert shopee.parse_search_items({"items": None}) == []


def test_price_strings_are_parseable_by_price_history():
    assert parse_price_value("$18,500") == 18500.0
    assert parse_price_value("$30,000 - $45,500") == 30000.0
    assert parse_price_value("¥1,200") == 1200.0
    assert parse_price_value("价格异常") is None


def test_parse_item_detail_and_shop_info():
    payload = _load("shopee_detail.json")
    detail = shopee.parse_item_detail(payload)
    assert detail["商品标题"].endswith("電池健康 92%")
    assert detail["商品描述"] == "自用機，無維修紀錄，附原廠充電器。"
    assert len(detail["商品图片列表"]) == 3
    assert detail["当前售价"] == "$18,500"
    assert detail["已售数量"] == 13 and detail["“想要”人数"] == 46
    assert detail["商品状况"] == "二手" and detail["品牌"] == "Apple"
    assert detail["商品属性"] == {"保固": "無"}
    assert detail["规格列表"] == [{"规格": "太空灰", "价格": "$18,500", "库存": 2}]

    shop = shopee.parse_shop_info(payload)
    assert shop["卖家昵称"] == "阿明的3C小舖" and shop["卖家ID"] == "222"
    assert shop["聊天回应率"] == "98%" and shop["粉丝数"] == 1234
    assert shop["卖家注册时长"].startswith("加入蝦皮")


def test_parse_detail_handles_missing_data():
    assert shopee.parse_item_detail({"error": 90309999}) == {}
    assert shopee.parse_shop_info({"data": {}}) == {}


def test_filter_search_items_by_shipping_and_region():
    items = shopee.parse_search_items(_load("shopee_search.json"))
    assert [i["商品ID"] for i in shopee.filter_search_items(items, free_shipping=True)] == ["111"]
    assert [i["商品ID"] for i in shopee.filter_search_items(items, region_filter="高雄市")] == ["333"]
    assert len(shopee.filter_search_items(items, region_filter="台北市/高雄市")) == 2
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
