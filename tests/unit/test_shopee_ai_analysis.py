"""Offline tests for the production Shopee AI boundary and capability negotiation."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from src.infrastructure.external.ai_client import AIClient
from src.services.ai_analysis_validator import InvalidAIAnalysisError, parse_validated_analysis, validate_analysis
from src.services.ai_request_compat import (
    AIRequestCompatibility, CHAT_COMPLETIONS_API_MODE, RESPONSES_API_MODE,
    build_ai_request_params, is_chat_completions_api_unsupported_error,
)
from src.services.remote_image_urls import safe_public_https_url


PRODUCT = {"platform": "shopee_tw", "product_id": "42", "title": "Mac mini M4", "seller": {}}
ANALYSIS = {
    "prompt_version": "EagleEye-TW-1.0", "is_recommended": False,
    "reason": "賣家與保固資訊不足，購買前請確認", "risk_tags": [],
    "information_gaps": ["保固資料"],
    "criteria_analysis": {
        "seller_type": {"status": "UNKNOWN", "comment": "資訊不足", "evidence": None},
        "seller_credit": {"status": "UNKNOWN", "comment": "資訊不足", "evidence": None},
    },
}


@pytest.mark.parametrize("model", ["o1", "o1-mini", "o3-2025-04-16", "o4-mini", "gpt-5", "gpt-5.1", "openai/gpt-5-mini"])
def test_reasoning_models_use_completion_tokens_without_sampling(model):
    params = build_ai_request_params(CHAT_COMPLETIONS_API_MODE, model=model,
        messages=[{"role": "user", "content": "JSON"}], temperature=0.1, max_output_tokens=4000)
    assert params["max_completion_tokens"] == 4000
    assert "max_tokens" not in params and "temperature" not in params


def test_responses_always_uses_output_token_field():
    params = build_ai_request_params(RESPONSES_API_MODE, model="gpt-5", messages=[], max_output_tokens=4000,
                                    chat_token_parameter="max_tokens", enable_json_output=True)
    assert params["max_output_tokens"] == 4000
    assert "max_tokens" not in params and "max_completion_tokens" not in params
    assert params["text"]["format"]["type"] == "json_object"


def test_gateway_alias_adapts_both_token_directions_without_looping():
    state = AIRequestCompatibility("gateway-alias", True)
    assert state.build([])["max_tokens"] == 4000
    error = Exception("Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead")
    assert state.adapt(error)
    assert "max_completion_tokens" in state.build([])
    assert not state.adapt(Exception("max_completion_tokens is unsupported"))
    known = AIRequestCompatibility("gpt-5", False)
    assert known.adapt(Exception("Unknown parameter: max_completion_tokens"))
    assert "max_tokens" in known.build([])


def test_structured_errors_remove_temperature_and_responses_json():
    state = AIRequestCompatibility("alias", True)
    assert state.adapt(Exception("404 page not found"))
    class Rejected(Exception):
        body = {"error": {"param": "text.format", "message": "Invalid parameter"}}
    assert state.adapt(Rejected())
    assert "text" not in state.build([])
    class TemperatureRejected(Exception):
        body = {"param": "temperature", "code": "unsupported_value"}
    assert state.adapt(TemperatureRejected())
    assert "temperature" not in state.build([])


def test_does_not_treat_auth_or_rate_limit_urls_as_missing_endpoints():
    for status in (401, 403, 429, 500):
        error = Exception("POST https://example.com/v1/chat/completions: failed")
        error.status_code = status
        assert not is_chat_completions_api_unsupported_error(error)
        assert not AIRequestCompatibility("alias", True).adapt(error)
    assert not AIRequestCompatibility("alias", True).adapt(Exception("model not found"))


def test_api_modes_do_not_oscillate():
    state = AIRequestCompatibility("alias", False)
    assert state.adapt(Exception("404 page not found"))
    assert state.api_mode == RESPONSES_API_MODE
    assert not state.adapt(Exception("404 page not found"))


def test_multiple_parameter_fallbacks_then_response_success():
    instance = AIClient.__new__(AIClient)
    instance.settings = SimpleNamespace(model_name="alias", enable_response_format=True)
    history = []
    async def create(**kwargs):
        history.append(kwargs)
        if "max_tokens" in kwargs:
            raise Exception("max_tokens not supported, use max_completion_tokens")
        if "response_format" in kwargs:
            raise Exception("response_format unsupported")
        if "temperature" in kwargs:
            raise Exception("temperature unsupported")
        return SimpleNamespace(output_text="ok")
    instance.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert asyncio.run(instance._call_ai([{"role": "user", "content": "JSON"}])) == "ok"
    assert len(history) == 4


def test_strict_analysis_retains_absent_seller_without_fabrication():
    original = copy.deepcopy(PRODUCT)
    assert parse_validated_analysis(json.dumps(ANALYSIS), PRODUCT) == ANALYSIS
    assert PRODUCT == original


@pytest.mark.parametrize("change", [
    {"is_recommended": "false"}, {"is_recommended": 1}, {"reason": ""},
    {"risk_tags": [1]}, {"risk_tags": "none"}, {"prompt_version": None},
    {"criteria_analysis": []}, {"information_gaps": [None]},
    {"value_score": float("inf")}, {"value_score": True},
])
def test_strict_field_types(change):
    with pytest.raises(InvalidAIAnalysisError):
        validate_analysis({**ANALYSIS, **change}, PRODUCT)


@pytest.mark.parametrize("content", [
    "[]", "null", "true", json.dumps(ANALYSIS) + json.dumps(ANALYSIS),
    "result: " + json.dumps(ANALYSIS), '{"is_recommended":true,"is_recommended":false}',
    '{"is_recommended":NaN}',
])
def test_strict_json_rejects_ambiguous_or_nonobjects(content):
    with pytest.raises(InvalidAIAnalysisError):
        parse_validated_analysis(content, PRODUCT)


def test_strict_json_accepts_single_fenced_object():
    assert parse_validated_analysis("```json\n" + json.dumps(ANALYSIS) + "\n```", PRODUCT) == ANALYSIS


@pytest.mark.parametrize("field", ["seller_type", "seller_credit"])
def test_absent_seller_data_cannot_support_an_explicit_verdict(field):
    value = copy.deepcopy(ANALYSIS)
    value["criteria_analysis"][field] = {"status": "PASS", "comment": "可信", "evidence": "臆測"}
    with pytest.raises(InvalidAIAnalysisError):
        validate_analysis(value, PRODUCT)


def test_known_seller_uses_source_evidence():
    product = {**PRODUCT, "seller": {"verified_type": "business", "rating": 4.7}}
    value = copy.deepcopy(ANALYSIS)
    value["criteria_analysis"]["seller_type"] = {"status": "PASS", "comment": "商家", "evidence": "verified_type=business"}
    value["criteria_analysis"]["seller_credit"] = {"status": "PASS", "comment": "公開評分", "evidence": "rating=4.7"}
    validate_analysis(value, product)


@pytest.mark.parametrize("url", ["http://example.com/photo.jpg", "https://127.0.0.1/p", "https://127.1/p", "https://0x7f.1/p", "https://localhost/p", "https://foo.local/p", "https://foo.internal/p", "https://user:pass@example.com/p", "https://example.com:8000/p", "file:///etc/passwd", "https://example.com/white space", "https://[::1]/p"])
def test_remote_images_reject_local_or_unsafe_urls(url):
    assert safe_public_https_url(url) is None


def test_image_toggle_uses_remote_multimodal_without_downloading():
    instance = AIClient.__new__(AIClient)
    url = "https://down-tw.img.susercontent.com/file/test.jpg"
    messages = instance._build_messages(PRODUCT, [], "JSON", remote_image_urls=[url, "https://localhost/p"])
    content = messages[0]["content"]
    assert content[0] == {"type": "image_url", "image_url": {"url": url}}
    assert isinstance(instance._build_messages(PRODUCT, [], "JSON")[0]["content"], str)


def test_analyze_rejects_invented_seller_and_never_returns_a_recommendation():
    instance = AIClient.__new__(AIClient)
    instance.client = object()
    bad = copy.deepcopy(ANALYSIS)
    bad["criteria_analysis"]["seller_type"] = {"status": "PASS", "comment": "個人", "evidence": "fake"}
    async def create(_messages):
        return json.dumps(bad)
    instance._call_ai = create
    assert asyncio.run(instance.analyze(PRODUCT, [], "JSON")) is None


def test_source_seller_type_is_reliable_without_an_unrelated_badge():
    value = copy.deepcopy(ANALYSIS)
    value["criteria_analysis"]["seller_type"] = {"status": "PASS", "comment": "個人", "evidence": "seller_type=personal"}
    validate_analysis(value, {**PRODUCT, "seller": {"seller_type": "personal"}})
    with pytest.raises(InvalidAIAnalysisError):
        validate_analysis(value, {**PRODUCT, "seller": {"verified_type": "verified"}})


def test_malformed_criterion_status_is_a_validation_error():
    value = copy.deepcopy(ANALYSIS)
    value["criteria_analysis"]["seller_type"]["status"] = []
    with pytest.raises(InvalidAIAnalysisError):
        validate_analysis(value, PRODUCT)


def test_responses_only_model_can_switch_from_400_endpoint_error():
    error = Exception("This model is not supported in the /v1/chat/completions endpoint. Use /v1/responses instead.")
    error.status_code = 400
    state = AIRequestCompatibility("gpt-5-pro", False)
    assert state.adapt(error)
    assert state.api_mode == RESPONSES_API_MODE
