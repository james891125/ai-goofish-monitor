import asyncio

from src.infrastructure.external.notification_clients.base import NotificationClient
from src.infrastructure.external.notification_clients.webhook_client import WebhookClient
from src.services.notification_service import NotificationService


class _OkClient(NotificationClient):
    channel_key = "ok"
    display_name = "OK"

    async def send(self, product_data, reason):
        return None


class _FailClient(NotificationClient):
    channel_key = "fail"
    display_name = "FAIL"

    async def send(self, product_data, reason):
        raise RuntimeError("boom")


def test_notification_service_collects_success_and_failure_results():
    service = NotificationService([_OkClient(enabled=True), _FailClient(enabled=True)])

    results = asyncio.run(
        service.send_notification({"商品標題": "Sony A7M4"}, "價格合適")
    )

    assert results["ok"]["success"] is True
    assert results["ok"]["message"] == "傳送成功"
    assert results["fail"]["success"] is False
    assert results["fail"]["message"] == "boom"


def test_webhook_client_renders_json_templates(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

    def _fake_post(url, headers=None, json=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["data"] = data
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)

    client = WebhookClient(
        webhook_url="https://hooks.example.com/notify",
        webhook_method="POST",
        webhook_headers='{"Authorization":"Bearer token"}',
        webhook_content_type="JSON",
        webhook_query_parameters='{"task":"{{title}}"}',
        webhook_body='{"message":"{{content}}","link":"{{desktop_link}}"}',
    )

    asyncio.run(
        client.send(
            {
                "商品標題": "Sony A7M4",
                "目前售價": "9999",
                "商品連結": "https://shopee.tw/product/1/123",
            },
            "價格合適",
        )
    )

    assert "Sony+A7M4" in captured["url"] and "task=%F0%9F%9A%A8" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["json"]["message"].startswith("價格: 9999")
    assert captured["json"]["link"] == "https://shopee.tw/product/1/123"
    assert captured["data"] is None
