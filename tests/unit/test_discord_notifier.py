import asyncio
import logging

import httpx
import pytest

from src.services import discord_notifier as discord

WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/" + "unit-test-only-token_" * 3
PRODUCT = {"title": "Mac mini M4 @everyone", "price_twd": 15000, "product_url": "https://shopee.tw/product/1/2",
           "images": ["https://down-tw.img.susercontent.com/file/test.jpg"], "collected_at": "2026-11-10T10:00:00+08:00"}
ANALYSIS = {"is_recommended": True, "reason": "符合需求", "risk_tags": ["保固待確認"]}


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/1/" + "x" * 40,
    "https://discord.com.evil.com/api/webhooks/1/" + "x" * 40,
    "https://user:secret@discord.com/api/webhooks/1/" + "x" * 40,
    WEBHOOK + "?redirect=http://localhost", WEBHOOK + "#fragment",
    "https://127.0.0.1/api/webhooks/1/" + "x" * 40,
    "https://discord.com:8000/api/webhooks/1/" + "x" * 40,
    "https://discord.com/api/webhooks/../foo", "", None,
])
def test_invalid_webhook_destinations(url):
    assert not discord.validate_discord_webhook_url(url)


def test_embed_contains_fields_and_cannot_mention_everyone():
    value = discord.build_discord_payload(PRODUCT, ANALYSIS)
    embed = value["embeds"][0]
    assert value["allowed_mentions"]["parse"] == []
    assert embed["url"] == PRODUCT["product_url"]
    assert embed["thumbnail"]["url"] == PRODUCT["images"][0]
    assert embed["fields"][0]["value"] == "NT$15,000"
    assert embed["fields"][1]["value"] == "值得考慮"
    assert "保固待確認" in embed["fields"][2]["value"]
    assert embed["timestamp"] == "2026-11-10T02:00:00+00:00"


def test_disallowed_images_and_unsafe_links_are_omitted():
    value = discord.build_discord_payload({**PRODUCT, "product_url": "https://example.com/phishing", "images_allowed": False}, ANALYSIS)
    assert "url" not in value["embeds"][0]
    assert "thumbnail" not in value["embeds"][0]


def test_payload_stays_under_discord_limits():
    payload = discord.build_discord_payload({**PRODUCT, "title": "x" * 1000}, {**ANALYSIS, "reason": "x" * 10000, "risk_tags": ["x" * 10000]})
    embed = payload["embeds"][0]
    assert len(embed["title"]) <= 256
    assert len(embed["description"]) <= 4096
    assert all(len(field["value"]) <= 1024 for field in embed["fields"])


def _mock_http(monkeypatch, responder):
    original = httpx.AsyncClient
    history = []
    def handler(request):
        history.append(request)
        return responder(request, len(history))
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(discord.httpx, "AsyncClient", factory)
    return history


def test_successful_discord_post_and_redacted_httpx_logs(monkeypatch, caplog):
    history = _mock_http(monkeypatch, lambda req, n: httpx.Response(204))
    caplog.set_level(logging.INFO, logger="httpx")
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, WEBHOOK)) is True
    assert len(history) == 1
    assert "allowed_mentions" in history[0].content.decode()
    assert WEBHOOK not in caplog.text
    assert "unit-test-only-token" not in caplog.text


def test_429_is_retried_once_for_short_wait(monkeypatch):
    history = _mock_http(monkeypatch, lambda req, n: httpx.Response(429, json={"retry_after": 0}) if n == 1 else httpx.Response(204))
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, WEBHOOK)) is True
    assert len(history) == 2


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 500])
def test_errors_and_redirects_are_not_retried(monkeypatch, status):
    history = _mock_http(monkeypatch, lambda req, n: httpx.Response(status, headers={"Location": "https://localhost/"}))
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, WEBHOOK)) is False
    assert len(history) == 1


def test_timeout_does_not_duplicate_uncertain_delivery_or_log_secret(monkeypatch, caplog):
    def timeout(req, n):
        raise httpx.ReadTimeout("secret " + WEBHOOK, request=req)
    history = _mock_http(monkeypatch, timeout)
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, WEBHOOK)) is False
    assert len(history) == 1
    assert WEBHOOK not in caplog.text


def test_invalid_url_never_constructs_network_client(monkeypatch):
    def fail(**kwargs):
        pytest.fail("Invalid webhook caused a network request")
    monkeypatch.setattr(discord.httpx, "AsyncClient", fail)
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, "https://localhost/webhook")) is False


def test_explicit_https_port_is_also_redacted(monkeypatch, caplog):
    _mock_http(monkeypatch, lambda req, n: httpx.Response(204))
    caplog.set_level(logging.INFO, logger="httpx")
    assert asyncio.run(discord.send(PRODUCT, ANALYSIS, WEBHOOK.replace("discord.com/", "discord.com:443/")))
    assert "unit-test-only-token" not in caplog.text


def test_keyword_result_is_not_labeled_ai_recommendation():
    payload=discord.build_discord_payload({'title':'測試','price_twd':100},{'recommended':True,'mode':'keyword','reason':'條件符合'})
    fields=payload['embeds'][0]['fields']
    assert any(field['name']=='關鍵字篩選' and '未進行 AI 分析' in field['value'] for field in fields)
