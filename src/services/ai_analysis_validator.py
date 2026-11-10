"""Validate analysis before it can become a recommendation or notification.

The parser used for generic gateway text remains tolerant for legacy callers.
Product recommendations require one JSON object, strict types and no fabricated
seller classifications when the authorized source supplies no evidence.
"""
import json
import math
from typing import Any


class InvalidAIAnalysisError(ValueError):
    """The model output is unsafe or insufficient to use as a recommendation."""


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidAIAnalysisError("AI JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_constant(_value):
    raise InvalidAIAnalysisError("AI JSON contains a non-finite number")


def parse_validated_analysis(content: str, product: dict | None = None) -> dict:
    """Accept optional enclosing fences, but reject prose or multiple decisions."""
    cleaned = content.strip()
    if cleaned.startswith("```json") and cleaned.endswith("```"):
        cleaned = cleaned[7:-3].strip()
    elif cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    try:
        parsed = json.loads(cleaned, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidAIAnalysisError("AI 必須回傳單一有效 JSON 物件") from exc
    validate_analysis(parsed, product)
    return parsed


def validate_analysis(analysis: Any, product: dict | None = None) -> None:
    """Raise on malformed output; never coerce a string 'false' into True."""
    if not isinstance(analysis, dict):
        raise InvalidAIAnalysisError("AI 分析必須為物件")
    for field in ("prompt_version", "reason"):
        if not isinstance(analysis.get(field), str) or not analysis[field].strip():
            raise InvalidAIAnalysisError(f"AI 分析缺少有效 {field}")
    if type(analysis.get("is_recommended")) is not bool:
        raise InvalidAIAnalysisError("is_recommended 必須為布林值")
    tags = analysis.get("risk_tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise InvalidAIAnalysisError("risk_tags 必須為文字陣列")
    criteria = analysis.get("criteria_analysis")
    if not isinstance(criteria, dict) or not criteria or "seller_type" not in criteria:
        raise InvalidAIAnalysisError("criteria_analysis 必須包含 seller_type")
    for key, value in criteria.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, (dict, str)) or not value:
            raise InvalidAIAnalysisError("criteria_analysis 含有無效項目")
    gaps = analysis.get("information_gaps", [])
    if not isinstance(gaps, list) or any(not isinstance(gap, str) or not gap.strip() for gap in gaps):
        raise InvalidAIAnalysisError("information_gaps 必須為文字陣列")
    if "value_score" in analysis:
        score = analysis["value_score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
            raise InvalidAIAnalysisError("value_score 必須介於 0 到 100")
    if "value_summary" in analysis and not isinstance(analysis["value_summary"], str):
        raise InvalidAIAnalysisError("value_summary 必須為文字")

    if product is None or product.get("platform") != "shopee_tw":
        return  # Retain the legacy custom-prompt shape for historical records.

    for value in criteria.values():
        if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value["status"] not in {"PASS", "FAIL", "UNKNOWN"}:
            raise InvalidAIAnalysisError("蝦皮分析項目必須使用 PASS、FAIL 或 UNKNOWN")
        if not isinstance(value.get("comment"), str) or not value["comment"].strip():
            raise InvalidAIAnalysisError("蝦皮分析項目必須附上說明")
        if "evidence" not in value or (value["evidence"] is not None and not isinstance(value["evidence"], str)):
            raise InvalidAIAnalysisError("蝦皮分析證據必須為文字或 null")
        if value["status"] != "UNKNOWN" and not value["evidence"]:
            raise InvalidAIAnalysisError("明確判斷必須附上資料來源中的證據")
    if "seller_credit" not in criteria:
        raise InvalidAIAnalysisError("蝦皮分析必須包含 seller_credit")
    seller = product.get("seller") or {}
    if not isinstance(seller, dict):
        seller = {}
    seller_type = criteria["seller_type"]
    reliable_type = seller.get("seller_type") in ("personal", "business") or seller.get("verified_type") in (
        "personal", "individual", "business", "merchant", "shopee_mall", "mall", "個人", "商家",
    )
    if not reliable_type:
        if seller_type["status"] != "UNKNOWN" or seller_type.get("persona") not in (None, "資訊不足", "未知"):
            raise InvalidAIAnalysisError("缺少可靠賣家類型證據，必須標示資訊不足")
    if seller.get("rating") is None and seller.get("review_count") is None:
        if criteria["seller_credit"]["status"] != "UNKNOWN":
            raise InvalidAIAnalysisError("缺少賣家公開信用資料，必須標示資訊不足")
