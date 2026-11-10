from src.services.recommendation_rules import apply_score_threshold, precheck_reject


def _record(title, **extra):
    return {"商品資訊": {"商品標題": title, **extra}}


def test_precheck_rejects_broken_preorder_and_sold_out_items(monkeypatch):
    monkeypatch.delenv("EXCLUDE_TITLE_WORDS", raising=False)

    broken = precheck_reject(_record("【故障零件機】Mac Mini 2018 無法開機"))
    preorder = precheck_reject(_record("Apple Mac mini M4【預購】"))
    sold_out = precheck_reject(_record("Mac mini M4", 已售完=True))

    for result in (broken, preorder, sold_out):
        assert result["is_recommended"] is False
        assert result["analysis_source"] == "rule" and "未使用 AI" in result["reason"]
    assert precheck_reject(_record("Apple Mac mini M4 16G/256G 全新")) is None


def test_exclude_words_are_configurable(monkeypatch):
    monkeypatch.setenv("EXCLUDE_TITLE_WORDS", "福利品，展示機")
    assert precheck_reject(_record("Mac mini 展示機")) is not None
    assert precheck_reject(_record("Mac mini 故障")) is None  # 預設清單被覆蓋
    monkeypatch.setenv("EXCLUDE_TITLE_WORDS", "")
    assert precheck_reject(_record("Mac mini 展示機")) is None


def test_score_below_threshold_overrides_recommendation(monkeypatch):
    monkeypatch.setenv("AI_RECOMMEND_MIN_SCORE", "60")

    low = apply_score_threshold({"is_recommended": True, "reason": "規格相符", "value_score": 45})
    high = apply_score_threshold({"is_recommended": True, "reason": "好", "value_score": "85"})
    missing = apply_score_threshold({"is_recommended": True, "reason": "沒給分"})

    assert low["is_recommended"] is False and "低於推薦門檻" in low["reason"]
    assert high["is_recommended"] is True and high["value_score"] == 85
    assert missing["is_recommended"] is True

    monkeypatch.setenv("AI_RECOMMEND_MIN_SCORE", "0")
    assert apply_score_threshold({"is_recommended": True, "reason": "x", "value_score": 5})["is_recommended"] is True
