"""
推薦判斷的兩道固定規則，不依賴 AI 的心情：

1. precheck_reject：標題含「故障、零件機、預購…」或已售完的商品，直接判為不推薦，
   不取詳情之外的任何 AI 呼叫，也就不花 token。
2. apply_score_threshold：AI 回報的符合度分數（value_score）低於門檻時，強制改成不推薦。
"""
import os
from typing import Optional

DEFAULT_EXCLUDE_WORDS = (
    "故障", "零件機", "無法開機", "不能開機", "殺肉", "拆零件", "維修用",
    "預購", "預訂", "訂金", "僅供參考", "僅供展示", "佔位", "占位",
)
DEFAULT_MIN_SCORE = 60


def exclude_words() -> list[str]:
    """EXCLUDE_TITLE_WORDS 未設定時用預設清單；設成空字串代表完全不排除。"""
    raw = os.getenv("EXCLUDE_TITLE_WORDS")
    if raw is None:
        return list(DEFAULT_EXCLUDE_WORDS)
    return [w.strip() for w in raw.replace("，", ",").split(",") if w.strip()]


def min_score() -> int:
    try:
        return max(0, int(os.getenv("AI_RECOMMEND_MIN_SCORE", str(DEFAULT_MIN_SCORE))))
    except ValueError:
        return DEFAULT_MIN_SCORE


def precheck_reject(record: dict) -> Optional[dict]:
    """命中規則時回傳「不推薦」的分析結果，否則回傳 None（交給 AI 判斷）。"""
    item = record.get("商品資訊") or {}
    title = str(item.get("商品標題") or "")
    lowered = title.lower()
    for word in exclude_words():
        if word.lower() in lowered:
            return _reject(f"標題含「{word}」，不是可以直接購買的完整商品（規則排除，未使用 AI）")
    if item.get("已售完"):
        return _reject("商品已售完（規則排除，未使用 AI）")
    return None


def _reject(reason: str) -> dict:
    return {
        "analysis_source": "rule",
        "is_recommended": False,
        "reason": reason,
        "value_score": 0,
        "risk_tags": ["規則排除"],
        "keyword_hit_count": 0,
    }


def _as_score(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_score_threshold(ai_result: dict) -> dict:
    """AI 推薦但分數低於門檻時改成不推薦；沒給分數時不動，只在理由裡註明。"""
    threshold = min_score()
    score = _as_score(ai_result.get("value_score"))
    if score is None or threshold <= 0:
        return ai_result
    ai_result["value_score"] = int(round(max(0.0, min(100.0, score))))
    if ai_result.get("is_recommended") is True and ai_result["value_score"] < threshold:
        ai_result["is_recommended"] = False
        ai_result["reason"] = (
            f"符合度 {ai_result['value_score']} 分，低於推薦門檻 {threshold} 分。"
            f"{ai_result.get('reason', '')}"
        ).strip()
    return ai_result
