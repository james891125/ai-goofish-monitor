from src.services.price_history_service import (
    build_item_price_context,
    build_price_history_insights,
    load_price_snapshots,
    record_market_snapshots,
)


def test_record_market_snapshots_and_build_price_history_insights(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen_item_ids = set()

    run1_items = [
        {
            "商品ID": "1001",
            "商品標題": "Sony A7M4 單機",
            "目前售價": "$10000",
            "商品標籤": ["驗貨寶"],
            "出貨地區": "台北",
            "賣家暱稱": "賣家A",
            "商品連結": "https://shopee.tw/product/1/1001",
            "釋出時間": "2026-01-01 09:00",
        },
        {
            "商品ID": "1002",
            "商品標題": "Sony A7M4 套機",
            "目前售價": "$12000",
            "商品標籤": ["包郵"],
            "出貨地區": "高雄",
            "賣家暱稱": "賣家B",
            "商品連結": "https://shopee.tw/product/1/1002",
            "釋出時間": "2026-01-01 10:00",
        },
    ]
    run2_items = [
        {
            "商品ID": "1001",
            "商品標題": "Sony A7M4 單機",
            "目前售價": "$9500",
            "商品標籤": ["驗貨寶"],
            "出貨地區": "台北",
            "賣家暱稱": "賣家A",
            "商品連結": "https://shopee.tw/product/1/1001",
            "釋出時間": "2026-01-02 09:00",
        },
        {
            "商品ID": "1003",
            "商品標題": "Sony A7M4 全套",
            "目前售價": "$13000",
            "商品標籤": ["同城"],
            "出貨地區": "南京",
            "賣家暱稱": "賣家C",
            "商品連結": "https://shopee.tw/product/1/1003",
            "釋出時間": "2026-01-02 11:00",
        },
    ]

    inserted_run1 = record_market_snapshots(
        keyword="sony a7m4",
        task_name="Sony A7M4 監控",
        items=run1_items,
        run_id="run-1",
        snapshot_time="2026-01-01T12:00:00",
        seen_item_ids=seen_item_ids,
    )
    assert len(inserted_run1) == 2

    inserted_run2 = record_market_snapshots(
        keyword="sony a7m4",
        task_name="Sony A7M4 監控",
        items=run2_items,
        run_id="run-2",
        snapshot_time="2026-01-02T12:00:00",
        seen_item_ids=set(),
    )
    assert len(inserted_run2) == 2

    snapshots = load_price_snapshots("sony a7m4")
    assert len(snapshots) == 4

    insights = build_price_history_insights("sony a7m4")
    assert insights["market_summary"]["sample_count"] == 2
    assert insights["market_summary"]["avg_price"] == 11250.0
    assert insights["market_summary"]["min_price"] == 9500.0
    assert insights["history_summary"]["unique_items"] == 3
    assert len(insights["daily_trend"]) == 2
    assert insights["daily_trend"][0]["day"] == "2026-01-01"
    assert insights["daily_trend"][1]["day"] == "2026-01-02"

    item_context = build_item_price_context(
        snapshots,
        item_id="1001",
        current_price=9500.0,
    )
    assert item_context["observation_count"] == 2
    assert item_context["min_price"] == 9500.0
    assert item_context["max_price"] == 10000.0
    assert item_context["price_change_amount"] == -500.0
    assert item_context["deal_label"] == "高價效比"
