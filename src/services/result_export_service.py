"""
結果匯出服務
"""
import csv
from io import StringIO


EXPORT_HEADERS = [
    "任務名稱",
    "搜尋關鍵字",
    "商品ID",
    "商品標題",
    "目前售價",
    "釋出時間",
    "賣家暱稱",
    "AI是否推薦",
    "分析來源",
    "原因",
    "價格觀察次數",
    "價格最低值",
    "價格最高值",
    "市場均價",
    "價效比分數",
    "價效比標籤",
    "商品連結",
]


def build_results_csv(records: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_HEADERS)
    writer.writeheader()

    for record in records:
        item = record.get("商品資訊", {}) or {}
        seller = record.get("賣家資訊", {}) or {}
        ai_analysis = record.get("ai_analysis", {}) or {}
        price_insight = record.get("price_insight", {}) or {}
        writer.writerow(
            {
                "任務名稱": record.get("任務名稱", ""),
                "搜尋關鍵字": record.get("搜尋關鍵字", ""),
                "商品ID": item.get("商品ID", ""),
                "商品標題": item.get("商品標題", ""),
                "目前售價": item.get("目前售價", ""),
                "釋出時間": item.get("釋出時間", ""),
                "賣家暱稱": seller.get("賣家暱稱") or item.get("賣家暱稱", ""),
                "AI是否推薦": "是" if ai_analysis.get("is_recommended") else "否",
                "分析來源": ai_analysis.get("analysis_source", ""),
                "原因": ai_analysis.get("reason", ""),
                "價格觀察次數": price_insight.get("observation_count", ""),
                "價格最低值": price_insight.get("min_price", ""),
                "價格最高值": price_insight.get("max_price", ""),
                "市場均價": price_insight.get("market_avg_price", ""),
                "價效比分數": ai_analysis.get("value_score", price_insight.get("deal_score", "")),
                "價效比標籤": ai_analysis.get("value_summary", price_insight.get("deal_label", "")),
                "商品連結": item.get("商品連結", ""),
            }
        )

    return buffer.getvalue()
