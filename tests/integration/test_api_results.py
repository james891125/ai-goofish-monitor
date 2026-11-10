import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import results
from src.services.price_history_service import record_market_snapshots


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_results_filter_and_sort_for_keyword_recommendations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jsonl_dir = tmp_path / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    target_file = jsonl_dir / "demo_full_data.jsonl"

    records = [
        {
            "爬取時間": "2026-01-01T01:00:00",
            "商品資訊": {"目前售價": "$1000", "釋出時間": "2026-01-01 10:00"},
            "ai_analysis": {
                "analysis_source": "keyword",
                "is_recommended": True,
                "keyword_hit_count": 3,
                "reason": "命中 3 個關鍵詞",
            },
        },
        {
            "爬取時間": "2026-01-01T02:00:00",
            "商品資訊": {"目前售價": "$2000", "釋出時間": "2026-01-01 11:00"},
            "ai_analysis": {
                "analysis_source": "keyword",
                "is_recommended": True,
                "keyword_hit_count": 1,
                "reason": "命中 1 個關鍵詞",
            },
        },
        {
            "爬取時間": "2026-01-01T03:00:00",
            "商品資訊": {"目前售價": "$3000", "釋出時間": "2026-01-01 12:00"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": True,
                "reason": "AI推薦",
            },
        },
    ]
    _write_jsonl(target_file, records)

    app = FastAPI()
    app.include_router(results.router)
    client = TestClient(app)

    resp = client.get(
        "/api/results/demo_full_data.jsonl",
        params={"keyword_recommended_only": True, "sort_by": "keyword_hit_count", "sort_order": "desc"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 2
    assert data["items"][0]["ai_analysis"]["keyword_hit_count"] == 3
    assert data["items"][1]["ai_analysis"]["keyword_hit_count"] == 1

    resp = client.get(
        "/api/results/demo_full_data.jsonl",
        params={"ai_recommended_only": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 1
    assert data["items"][0]["ai_analysis"]["analysis_source"] == "ai"

    resp = client.get(
        "/api/results/demo_full_data.jsonl",
        params={"ai_recommended_only": True, "keyword_recommended_only": True},
    )
    assert resp.status_code == 400


def test_results_insights_and_export_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jsonl_dir = tmp_path / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    target_file = jsonl_dir / "demo_full_data.jsonl"

    records = [
        {
            "爬取時間": "2026-01-02T09:00:00",
            "搜尋關鍵字": "demo",
            "任務名稱": "Demo 任務",
            "商品資訊": {
                "商品ID": "1001",
                "商品標題": "Demo One",
                "商品連結": "https://shopee.tw/product/1/1001",
                "目前售價": "$950",
                "釋出時間": "2026-01-02 08:30",
            },
            "賣家資訊": {"賣家暱稱": "賣家A"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": True,
                "reason": "價格低於近期均價",
            },
        },
        {
            "爬取時間": "2026-01-02T09:05:00",
            "搜尋關鍵字": "demo",
            "任務名稱": "Demo 任務",
            "商品資訊": {
                "商品ID": "1002",
                "商品標題": "Demo Two",
                "商品連結": "https://shopee.tw/product/1/1002",
                "目前售價": "$1200",
                "釋出時間": "2026-01-02 08:45",
            },
            "賣家資訊": {"賣家暱稱": "賣家B"},
            "ai_analysis": {
                "analysis_source": "keyword",
                "is_recommended": False,
                "reason": "未命中",
                "keyword_hit_count": 0,
            },
        },
    ]
    _write_jsonl(target_file, records)

    record_market_snapshots(
        keyword="demo",
        task_name="Demo 任務",
        items=[
            {
                "商品ID": "1001",
                "商品標題": "Demo One",
                "目前售價": "$1000",
                "商品連結": "https://shopee.tw/product/1/1001",
            },
            {
                "商品ID": "1002",
                "商品標題": "Demo Two",
                "目前售價": "$1200",
                "商品連結": "https://shopee.tw/product/1/1002",
            },
        ],
        run_id="run-1",
        snapshot_time="2026-01-01T10:00:00",
        seen_item_ids=set(),
    )
    record_market_snapshots(
        keyword="demo",
        task_name="Demo 任務",
        items=[
            {
                "商品ID": "1001",
                "商品標題": "Demo One",
                "目前售價": "$950",
                "商品連結": "https://shopee.tw/product/1/1001",
            },
            {
                "商品ID": "1002",
                "商品標題": "Demo Two",
                "目前售價": "$1180",
                "商品連結": "https://shopee.tw/product/1/1002",
            },
        ],
        run_id="run-2",
        snapshot_time="2026-01-02T10:00:00",
        seen_item_ids=set(),
    )

    app = FastAPI()
    app.include_router(results.router)
    client = TestClient(app)

    insights_resp = client.get("/api/results/demo_full_data.jsonl/insights")
    assert insights_resp.status_code == 200
    insights = insights_resp.json()
    assert insights["market_summary"]["sample_count"] == 2
    assert len(insights["daily_trend"]) == 2

    list_resp = client.get("/api/results/demo_full_data.jsonl")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert items[0]["price_insight"]["observation_count"] >= 1

    export_resp = client.get(
        "/api/results/demo_full_data.jsonl/export",
        params={"sort_by": "price", "sort_order": "asc"},
    )
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    text = export_resp.text
    assert "任務名稱,搜尋關鍵字,商品ID,商品標題" in text
    assert "Demo One" in text
    # Excel 需要 BOM 才會把檔案當成 UTF-8，否則中文會變亂碼
    assert export_resp.content.startswith(b"\xef\xbb\xbf")


def test_results_export_csv_supports_unicode_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jsonl_dir = tmp_path / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    target_file = jsonl_dir / "演示_full_data.jsonl"

    records = [
        {
            "爬取時間": "2026-01-02T09:00:00",
            "搜尋關鍵字": "演示",
            "任務名稱": "演示任務",
            "商品資訊": {
                "商品ID": "1001",
                "商品標題": "演示商品",
                "商品連結": "https://shopee.tw/product/1/1001",
                "目前售價": "$950",
                "釋出時間": "2026-01-02 08:30",
            },
            "賣家資訊": {"賣家暱稱": "賣家A"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": True,
                "reason": "價格合理",
            },
        }
    ]
    _write_jsonl(target_file, records)

    app = FastAPI()
    app.include_router(results.router)
    client = TestClient(app)

    export_resp = client.get("/api/results/演示_full_data.jsonl/export")
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    disposition = export_resp.headers["content-disposition"]
    assert 'filename="export.csv"' in disposition
    assert "filename*=UTF-8''%E6%BC%94%E7%A4%BA_full_data.csv" in disposition


def test_results_blacklist_rules_hide_items_from_view_and_insights(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jsonl_dir = tmp_path / "jsonl"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    target_file = jsonl_dir / "macbook_air_m1_full_data.jsonl"

    records = [
        {
            "爬取時間": "2026-01-03T09:00:00",
            "搜尋關鍵字": "MacBook Air M1",
            "任務名稱": "MacBook Air M1 監控",
            "商品資訊": {
                "商品ID": "2001",
                "商品標題": "MacBook Air M1 8+256",
                "商品連結": "https://shopee.tw/product/1/2001",
                "目前售價": "$4200",
                "釋出時間": "2026-01-03 08:30",
            },
            "賣家資訊": {"賣家暱稱": "賣家A"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": True,
                "reason": "符合目標機型",
            },
        },
        {
            "爬取時間": "2026-01-03T09:05:00",
            "搜尋關鍵字": "MacBook Air M1",
            "任務名稱": "MacBook Air M1 監控",
            "商品資訊": {
                "商品ID": "2002",
                "商品標題": "MacBook Air Intel i5 8+256",
                "商品連結": "https://shopee.tw/product/1/2002",
                "目前售價": "$3100",
                "釋出時間": "2026-01-03 08:35",
            },
            "賣家資訊": {"賣家暱稱": "賣家B"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": False,
                "reason": "不是目標機型",
            },
        },
        {
            "爬取時間": "2026-01-03T09:10:00",
            "搜尋關鍵字": "MacBook Air M1",
            "任務名稱": "MacBook Air M1 監控",
            "商品資訊": {
                "商品ID": "2003",
                "商品標題": "MacBook Pro Intel 13寸",
                "商品連結": "https://shopee.tw/product/1/2003",
                "目前售價": "$3600",
                "釋出時間": "2026-01-03 08:40",
            },
            "賣家資訊": {"賣家暱稱": "賣家C"},
            "ai_analysis": {
                "analysis_source": "ai",
                "is_recommended": False,
                "reason": "不是 Air M1",
            },
        },
    ]
    _write_jsonl(target_file, records)

    record_market_snapshots(
        keyword="MacBook Air M1",
        task_name="MacBook Air M1 監控",
        items=[
            {
                "商品ID": "2001",
                "商品標題": "MacBook Air M1 8+256",
                "目前售價": "$4300",
                "商品連結": "https://shopee.tw/product/1/2001",
            },
            {
                "商品ID": "2002",
                "商品標題": "MacBook Air Intel i5 8+256",
                "目前售價": "$3200",
                "商品連結": "https://shopee.tw/product/1/2002",
            },
            {
                "商品ID": "2003",
                "商品標題": "MacBook Pro Intel 13寸",
                "目前售價": "$3700",
                "商品連結": "https://shopee.tw/product/1/2003",
            },
        ],
        run_id="run-1",
        snapshot_time="2026-01-02T10:00:00",
        seen_item_ids=set(),
    )
    record_market_snapshots(
        keyword="MacBook Air M1",
        task_name="MacBook Air M1 監控",
        items=[
            {
                "商品ID": "2001",
                "商品標題": "MacBook Air M1 8+256",
                "目前售價": "$4200",
                "商品連結": "https://shopee.tw/product/1/2001",
            },
            {
                "商品ID": "2002",
                "商品標題": "MacBook Air Intel i5 8+256",
                "目前售價": "$3100",
                "商品連結": "https://shopee.tw/product/1/2002",
            },
            {
                "商品ID": "2003",
                "商品標題": "MacBook Pro Intel 13寸",
                "目前售價": "$3600",
                "商品連結": "https://shopee.tw/product/1/2003",
            },
        ],
        run_id="run-2",
        snapshot_time="2026-01-03T10:00:00",
        seen_item_ids=set(),
    )

    app = FastAPI()
    app.include_router(results.router)
    client = TestClient(app)

    update_rules_resp = client.put(
        "/api/results/macbook_air_m1_full_data.jsonl/blacklist-rules",
        json={"keywords": ["intel"]},
    )
    assert update_rules_resp.status_code == 200
    assert update_rules_resp.json()["keywords"] == ["intel"]

    rules_resp = client.get("/api/results/macbook_air_m1_full_data.jsonl/blacklist-rules")
    assert rules_resp.status_code == 200
    assert rules_resp.json()["keywords"] == ["intel"]

    filtered_resp = client.get("/api/results/macbook_air_m1_full_data.jsonl")
    assert filtered_resp.status_code == 200
    filtered_payload = filtered_resp.json()
    assert filtered_payload["total_items"] == 1
    assert [item["商品資訊"]["商品ID"] for item in filtered_payload["items"]] == ["2001"]

    include_hidden_resp = client.get(
        "/api/results/macbook_air_m1_full_data.jsonl",
        params={"include_hidden": True},
    )
    assert include_hidden_resp.status_code == 200
    include_hidden_payload = include_hidden_resp.json()
    assert include_hidden_payload["total_items"] == 3
    hidden_item = next(
        item for item in include_hidden_payload["items"]
        if item["商品資訊"]["商品ID"] == "2002"
    )
    assert hidden_item["_hidden_reason"] == "rule"
    assert hidden_item["_matched_blacklist_keywords"] == ["intel"]

    insights_resp = client.get("/api/results/macbook_air_m1_full_data.jsonl/insights")
    assert insights_resp.status_code == 200
    insights = insights_resp.json()
    assert insights["market_summary"]["sample_count"] == 1
    assert insights["market_summary"]["avg_price"] == 4200.0
    assert all(point["sample_count"] == 1 for point in insights["daily_trend"])

    list_resp = client.get("/api/results/macbook_air_m1_full_data.jsonl")
    assert list_resp.status_code == 200
    visible_item = list_resp.json()["items"][0]
    assert visible_item["price_insight"]["market_avg_price"] == 4200.0

    export_resp = client.get("/api/results/macbook_air_m1_full_data.jsonl/export")
    assert export_resp.status_code == 200
    assert "MacBook Air M1 8+256" in export_resp.text
    assert "MacBook Air Intel i5 8+256" not in export_resp.text
    assert "MacBook Pro Intel 13寸" not in export_resp.text

    download_resp = client.get("/api/results/files/macbook_air_m1_full_data.jsonl")
    assert download_resp.status_code == 200
    assert "MacBook Air Intel i5 8+256" in download_resp.text
    assert "MacBook Pro Intel 13寸" in download_resp.text
