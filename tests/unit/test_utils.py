import asyncio

from src.services.result_storage_service import load_all_result_records
from src.utils import (
    get_link_unique_key,
    safe_get,
    save_to_jsonl,
)


def test_safe_get_nested_and_default():
    data = {"a": {"b": [{"c": "value"}]}}
    assert asyncio.run(safe_get(data, "a", "b", 0, "c")) == "value"
    assert asyncio.run(safe_get(data, "a", "b", 1, "c", default="missing")) == "missing"


def test_get_link_unique_key():
    link = "https://shopee.tw/product/1/123&foo=bar"
    assert get_link_unique_key(link) == "https://shopee.tw/product/1/123"


def test_save_to_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    record = {
        "爬取時間": "2026-01-01T10:00:00",
        "搜尋關鍵字": "sony a7m4",
        "任務名稱": "Sony A7M4",
        "商品資訊": {
            "商品ID": "1",
            "商品標題": "Sony A7M4",
            "商品連結": "https://shopee.tw/product/1/1",
            "目前售價": "$10000",
        },
    }

    ok = asyncio.run(save_to_jsonl(record, keyword="sony a7m4"))
    assert ok is True

    records = asyncio.run(
        load_all_result_records(
            "sony_a7m4_full_data.jsonl",
            ai_recommended_only=False,
            keyword_recommended_only=False,
            sort_by="crawl_time",
            sort_order="asc",
        )
    )
    stored = {k: v for k, v in records[0].items() if not k.startswith("_")}
    assert len(records) == 1 and stored == record
