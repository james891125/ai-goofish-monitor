import asyncio
import json
from pathlib import Path

import pytest

from shopee_lite import exporter, runner
from shopee_lite.ai import AIClient, parse_ai_reply
from shopee_lite.errors import RiskControlError
from shopee_lite.runner import RunOptions, run_search

FIX = Path(__file__).resolve().parent / "fixtures"


class FakeBrowser:
    def __init__(self, detail_payload=None, detail_error=None):
        self.search_urls = []
        self.detail_urls = []
        self.detail_payload = detail_payload
        self.detail_error = detail_error

    async def search(self, url):
        self.search_urls.append(url)
        return json.loads((FIX / "shopee_search.json").read_text(encoding="utf-8"))

    async def detail(self, url):
        self.detail_urls.append(url)
        if self.detail_error:
            raise self.detail_error
        return self.detail_payload

    async def pause(self, low, high):
        return None


def detail_payload(description="自用機，2025/03 購入，保固至2027/8，附原廠充電器"):
    payload = json.loads((FIX / "shopee_detail.json").read_text(encoding="utf-8"))
    payload["data"]["item"]["description"] = description
    return payload


def run(options, browser, ai=None):
    return asyncio.run(run_search(options, browser, ai, log=lambda m: None))


def test_title_only_mode_never_opens_product_pages():
    browser = FakeBrowser()
    result = run(RunOptions(["macbook"], pages=1, detail="off"), browser)

    assert browser.detail_urls == []
    row = result.rows[0]
    assert row["品名"].startswith("MacBook Air M1") and row["價格"] == 18500
    assert row["記憶體"] == "8GB" and row["儲存容量"] == "256GB" and row["狀態"] == "二手"
    assert row["資料來源"] == "標題"
    multi = result.rows[1]
    assert multi["價格"] == 30000 and multi["多規格最高價"] == 45500


def test_auto_mode_only_opens_pages_whose_title_lacks_info():
    browser = FakeBrowser(detail_payload=detail_payload("全新未拆，16G/512G，保固至2027/8"))
    result = run(RunOptions(["macbook"], pages=1, detail="auto"), browser)

    # 第一件標題已有狀態與容量，不需要進頁面；第二件「MacBook Pro 14 多規格」缺資訊才補
    assert len(browser.detail_urls) == 1 and "/444/333" in browser.detail_urls[0]
    filled = result.rows[1]
    assert filled["狀態"] == "全新" and filled["記憶體"] == "16GB" and filled["儲存容量"] == "512GB"
    assert filled["保固"] == "保固至 2027/08" and filled["資料來源"] == "標題+詳情頁"
    assert result.rows[0]["資料來源"] == "標題"


def test_all_mode_opens_every_page_and_reads_warranty_and_purchase_date():
    browser = FakeBrowser(detail_payload=detail_payload())
    result = run(RunOptions(["macbook"], pages=1, detail="all"), browser)

    assert len(browser.detail_urls) == 2
    first = result.rows[0]
    assert first["購買日期"] == "2025/03" and first["保固"] == "保固至 2027/08"


def test_risk_block_on_detail_keeps_title_data_and_stops_detail_phase():
    browser = FakeBrowser(detail_error=RiskControlError("blocked"))
    result = run(RunOptions(["macbook"], pages=1, detail="all"), browser)

    assert len(browser.detail_urls) == 1  # 被攔後不再繼續開頁
    assert len(result.rows) == 2 and all(r["資料來源"] == "標題" for r in result.rows)


def test_title_match_filter_and_duplicate_removal_across_keywords():
    browser = FakeBrowser()
    only_air = run(RunOptions(["macbook air"], pages=1, detail="off"), browser)
    assert [r["品名"][:11] for r in only_air.rows] == ["MacBook Air"]
    everything = run(RunOptions(["macbook air"], pages=1, detail="off", title_match=False), FakeBrowser())
    assert len(everything.rows) == 2
    twice = run(RunOptions(["macbook", "macbook pro"], pages=1, detail="off", title_match=False), FakeBrowser())
    assert len(twice.rows) == 2  # 同一商品不會因為不同關鍵字重複出現


def test_pages_are_clamped_and_urls_carry_filters():
    browser = FakeBrowser()
    options = RunOptions(["macbook"], pages=99, min_price="1000", max_price="5000", latest=True, detail="off")
    run(options, browser)
    assert options.pages == runner.MAX_PAGES and len(browser.search_urls) == runner.MAX_PAGES
    assert "minPrice=1000" in browser.search_urls[0] and "sortBy=ctime" in browser.search_urls[0]
    assert "page=9" in browser.search_urls[-1]
    with pytest.raises(ValueError):
        RunOptions([" "]).validate()


class FakeAI(AIClient):
    def __init__(self, replies):
        super().__init__("http://x", "k", "m")
        self.replies = replies
        self.batches = []

    async def extract_batch(self, items):
        self.batches.append(items)
        self.usage.requests += 1
        return self.replies


def test_ai_on_mode_fills_only_blanks_and_compare_mode_shows_differences():
    replies = {
        0: {"狀態": "全新", "記憶體": "8GB", "儲存容量": "256GB", "保固": "保固 1 年", "購買日期": ""},
        1: {"狀態": "二手", "記憶體": "16GB", "儲存容量": "512GB", "保固": "", "購買日期": ""},
    }
    ai = FakeAI(replies)
    on = run(RunOptions(["macbook"], pages=1, detail="off", ai="on", title_match=False), FakeBrowser(), ai)
    first, second = on.rows
    assert first["狀態"] == "二手"            # 規則已有值，AI 不覆蓋
    assert first["保固"] == "保固 1 年"        # 規則沒有，AI 補上
    assert second["記憶體"] == "16GB" and second["資料來源"].endswith("+AI")
    assert len(ai.batches) == 1 and set(ai.batches[0][0]) == {"id", "title", "desc"}  # 只送文字
    assert any("AI 回覆了 2/2" in line for line in on.summary)

    cmp_ = run(RunOptions(["macbook"], pages=1, detail="off", ai="compare", title_match=False), FakeBrowser(), FakeAI(replies))
    row = cmp_.rows[0]
    assert row["AI_狀態"] == "全新" and "狀態" in row["差異欄位"] and "記憶體" not in row["差異欄位"]
    header = exporter.build_csv(cmp_.rows, "compare").decode("utf-8-sig").splitlines()[0]
    assert "AI_狀態" in header and header.endswith("差異欄位")


def test_ai_without_key_is_skipped_with_a_note():
    result = run(RunOptions(["macbook"], pages=1, detail="off", ai="on"), FakeBrowser(), AIClient("", "", ""))
    assert result.mode == "off" and any("尚未設定 AI" in line for line in result.summary)


def test_parse_ai_reply_tolerates_code_fences_and_invalid_values():
    reply = '```json\n{"items":[{"id":0,"狀態":"很新","記憶體":"16GB","儲存容量":null,"保固":"保固中","購買日期":""}]}\n```'
    parsed = parse_ai_reply(reply)
    assert parsed[0]["狀態"] == "" and parsed[0]["記憶體"] == "16GB" and parsed[0]["儲存容量"] == ""
    with pytest.raises(ValueError):
        parse_ai_reply("抱歉我辦不到")


def test_accessory_filter_keeps_real_products():
    from shopee_lite.runner import is_accessory

    accessories = [
        "hoda 晶盾貼 Apple Watch S11 S10 Se 3D熱彎保護貼",
        "【MK3C】小香風四葉草錶帶⚡不鏽鋼錶帶 Apple Watch S11 S10",
        "RayCue Mac Mini M4/M4 Pro專用擴充底座",
        "全鋁CNC Mac mini M4 Pro 机箱升级版 預購 代購金",
        "（已售出）近全新Apple Watch S10 46mm GPS",
    ]
    products = [
        "台中 Apple Watch 10 GPS 46mm 64G黑色鋁金屬錶殼 S10 99%",
        "【艾爾巴二手】Apple Watch S10 A2999 46MM GPS 黑#智慧手錶#中壢店32M9K",
        "[龍龍3C] 蘋果 Apple Mac Mini M4 24G 512GB SSD 迷你主機 桌上型電腦 A3238",
        "技嘉平台 RTX5070 電競主機 Ultra 7/32G/1TB 靜音機殼 原價屋",
    ]
    assert all(is_accessory(t) for t in accessories)
    assert not any(is_accessory(t) for t in products)


def test_description_boilerplate_does_not_mark_item_as_broken_or_add_fake_sizes():
    from shopee_lite.extract import extract_fields

    desc = "七天鑑賞期，非人為故障享原廠保固一年。預購商品另計。傳輸速率 10Gb/s，贈 180G 雲端流量。"
    got = extract_fields(desc, from_description=True)
    assert got["狀態"] == "" and got["記憶體"] == "" and got["儲存容量"] == ""
    assert got["保固"] == "保固 1 年"
