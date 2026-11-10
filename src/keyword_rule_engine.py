"""
關鍵詞判斷引擎：單組 OR 邏輯，命中任意關鍵詞即推薦。
純英數字關鍵詞按完整詞匹配，避免 Q1 誤命中 Q1R5。
"""
import re
from typing import Any, Dict, Iterable, List


_ASCII_TOKEN_KEYWORD_PATTERN = re.compile(r"^[a-z0-9 ]+$")
_ASCII_TOKEN_BOUNDARY = r"[a-z0-9]"


def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def _collect_text_fragments(value: Any, bucket: List[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            bucket.append(text)
        return
    if isinstance(value, (int, float, bool)):
        bucket.append(str(value))
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_text_fragments(item, bucket)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_fragments(item, bucket)


def build_search_text(record: Dict[str, Any]) -> str:
    fragments: List[str] = []
    product_info = record.get("商品資訊", {})
    seller_info = record.get("賣家資訊", {})

    _collect_text_fragments(product_info.get("商品標題"), fragments)
    _collect_text_fragments(product_info, fragments)
    _collect_text_fragments(seller_info, fragments)

    return normalize_text(" ".join(fragments))


def _normalize_keywords(values: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw in values or []:
        text = normalize_text(str(raw).strip())
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _uses_ascii_token_match(keyword: str) -> bool:
    return bool(keyword) and _ASCII_TOKEN_KEYWORD_PATTERN.fullmatch(keyword) is not None


def _keyword_matches(keyword: str, normalized_text: str) -> bool:
    if not _uses_ascii_token_match(keyword):
        return keyword in normalized_text
    pattern = rf"(?<!{_ASCII_TOKEN_BOUNDARY}){re.escape(keyword)}(?!{_ASCII_TOKEN_BOUNDARY})"
    return re.search(pattern, normalized_text) is not None


def evaluate_keyword_rules(keywords: List[str], search_text: str) -> Dict[str, Any]:
    normalized_text = normalize_text(search_text)
    normalized_keywords = _normalize_keywords(keywords)

    if not normalized_text:
        return {
            "analysis_source": "keyword",
            "is_recommended": False,
            "reason": "可匹配文字為空，關鍵詞規則無法執行。",
            "matched_keywords": [],
            "keyword_hit_count": 0,
        }

    if not normalized_keywords:
        return {
            "analysis_source": "keyword",
            "is_recommended": False,
            "reason": "未配置關鍵詞規則。",
            "matched_keywords": [],
            "keyword_hit_count": 0,
        }

    matched_keywords = [kw for kw in normalized_keywords if _keyword_matches(kw, normalized_text)]
    hit_count = len(matched_keywords)
    is_recommended = hit_count > 0

    if is_recommended:
        reason = f"命中 {hit_count} 個關鍵詞：{', '.join(matched_keywords)}"
    else:
        reason = "未命中任何關鍵詞。"

    return {
        "analysis_source": "keyword",
        "is_recommended": is_recommended,
        "reason": reason,
        "matched_keywords": matched_keywords,
        "keyword_hit_count": hit_count,
    }
