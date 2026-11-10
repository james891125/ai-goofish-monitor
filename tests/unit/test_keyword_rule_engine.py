from src.keyword_rule_engine import build_search_text, evaluate_keyword_rules


def _sample_record():
    return {
        "商品資訊": {
            "商品標題": "Sony A7M4 全畫幅相機",
            "目前售價": "10000",
            "商品標籤": ["驗貨寶", "包郵"],
        },
        "賣家資訊": {
            "賣家暱稱": "攝影器材店",
            "賣家個性簽名": "可驗機，支援同城面交",
        },
    }


def test_build_search_text_contains_product_and_seller_fields():
    text = build_search_text(_sample_record())
    assert "sony a7m4" in text
    assert "攝影器材店" in text
    assert "支援同城面交" in text


def test_keyword_rules_or_match_any_keyword():
    text = build_search_text(_sample_record())
    result = evaluate_keyword_rules(["a7m4", "佳能"], text)
    assert result["is_recommended"] is True
    assert result["analysis_source"] == "keyword"
    assert result["keyword_hit_count"] == 1
    assert result["matched_keywords"] == ["a7m4"]


def test_keyword_rules_count_multiple_hits():
    text = build_search_text(_sample_record())
    result = evaluate_keyword_rules(["a7m4", "驗貨寶", "攝影器材店"], text)
    assert result["is_recommended"] is True
    assert result["keyword_hit_count"] == 3


def test_keyword_rules_case_insensitive_contains():
    text = build_search_text(_sample_record())
    result = evaluate_keyword_rules(["SONY", "A7M4"], text)
    assert result["is_recommended"] is True
    assert result["keyword_hit_count"] == 2


def test_keyword_rules_no_match():
    text = build_search_text(_sample_record())
    result = evaluate_keyword_rules(["佳能", "單反"], text)
    assert result["is_recommended"] is False
    assert result["keyword_hit_count"] == 0


def test_keyword_rules_do_not_partially_match_alphanumeric_prefixes():
    result = evaluate_keyword_rules(["q1"], "富士 q1r5 旗艦相機")
    assert result["is_recommended"] is False
    assert result["keyword_hit_count"] == 0


def test_keyword_rules_still_match_full_alphanumeric_token():
    result = evaluate_keyword_rules(["q1r5"], "富士 q1r5 旗艦相機")
    assert result["is_recommended"] is True
    assert result["keyword_hit_count"] == 1
