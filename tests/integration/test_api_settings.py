from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.api.routes import settings
from src.infrastructure.config.env_manager import env_manager


_SETTINGS_ENV_KEYS = [
    "ACCOUNT_ROTATION_ENABLED",
    "ACCOUNT_ROTATION_MODE",
    "ACCOUNT_ROTATION_RETRY_LIMIT",
    "ACCOUNT_BLACKLIST_TTL",
    "ACCOUNT_STATE_DIR",
    "PROXY_ROTATION_ENABLED",
    "PROXY_ROTATION_MODE",
    "PROXY_POOL",
    "PROXY_ROTATION_RETRY_LIMIT",
    "PROXY_BLACKLIST_TTL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL_NAME",
    "SKIP_AI_ANALYSIS",
    "PROXY_URL",
    "WEBHOOK_URL",
    "WEBHOOK_METHOD",
    "WEBHOOK_HEADERS",
    "WEBHOOK_CONTENT_TYPE",
    "WEBHOOK_QUERY_PARAMETERS",
    "WEBHOOK_BODY",
]


class _IdleProcessService:
    def __init__(self) -> None:
        self.processes = {}


def _build_settings_client() -> TestClient:
    app = FastAPI()
    app.include_router(settings.router)
    app.dependency_overrides[deps.get_process_service] = _IdleProcessService
    return TestClient(app)


def _clear_settings_env(monkeypatch) -> None:
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_rotation_settings_include_account_rotation_fields(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ACCOUNT_ROTATION_ENABLED=false",
                "ACCOUNT_ROTATION_MODE=per_task",
                "ACCOUNT_ROTATION_RETRY_LIMIT=2",
                "ACCOUNT_BLACKLIST_TTL=300",
                "ACCOUNT_STATE_DIR=state",
                "PROXY_ROTATION_ENABLED=false",
                "PROXY_ROTATION_MODE=per_task",
                "PROXY_ROTATION_RETRY_LIMIT=2",
                "PROXY_BLACKLIST_TTL=300",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)

    client = _build_settings_client()

    response = client.get("/api/settings/rotation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ACCOUNT_ROTATION_ENABLED"] is False
    assert payload["ACCOUNT_ROTATION_MODE"] == "per_task"
    assert payload["ACCOUNT_STATE_DIR"] == "state"

    update_response = client.put(
        "/api/settings/rotation",
        json={
            "ACCOUNT_ROTATION_ENABLED": True,
            "ACCOUNT_ROTATION_MODE": "on_failure",
            "ACCOUNT_ROTATION_RETRY_LIMIT": 4,
            "ACCOUNT_BLACKLIST_TTL": 900,
            "ACCOUNT_STATE_DIR": "accounts",
        },
    )
    assert update_response.status_code == 200

    latest = env_file.read_text(encoding="utf-8")
    assert "ACCOUNT_ROTATION_ENABLED=true" in latest
    assert "ACCOUNT_ROTATION_MODE=on_failure" in latest
    assert "ACCOUNT_ROTATION_RETRY_LIMIT=4" in latest
    assert "ACCOUNT_BLACKLIST_TTL=900" in latest
    assert "ACCOUNT_STATE_DIR=accounts" in latest







def test_ai_settings_fall_back_to_runtime_environment_when_env_file_missing(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(env_manager, "env_file", env_file)
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://runtime.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "runtime-model")
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:7890")
    client = _build_settings_client()

    ai_response = client.get("/api/settings/ai")
    assert ai_response.status_code == 200
    assert ai_response.json() == {
        "OPENAI_BASE_URL": "https://runtime.example.com/v1",
        "OPENAI_MODEL_NAME": "runtime-model",
        "SKIP_AI_ANALYSIS": False,
        "PROXY_URL": "http://127.0.0.1:7890",
    }

    status_response = client.get("/api/settings/status")
    assert status_response.status_code == 200
    env_payload = status_response.json()["env_file"]
    assert env_payload["exists"] is False
    assert env_payload["openai_api_key_set"] is True
    assert env_payload["openai_base_url_set"] is True
    assert env_payload["openai_model_name_set"] is True



def test_ai_test_endpoint_falls_back_to_responses_when_chat_completions_api_404(
    tmp_path, monkeypatch
):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()
    request_history = []

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = type(
                "_Responses",
                (),
                {"create": self._responses_create},
            )()
            self.chat = type(
                "_Chat",
                (),
                {
                    "completions": type(
                        "_Completions",
                        (),
                        {"create": self._chat_create},
                    )()
                },
            )()

        def _responses_create(self, **kwargs):
            request_history.append(("responses", kwargs))
            return type(
                "_Response",
                (),
                {"output_text": "OK"},
            )()

        def _chat_create(self, **kwargs):
            request_history.append(("chat", kwargs))
            raise Exception("Error code: 404 - page not found")

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    response = client.post(
        "/api/settings/ai/test",
        json={
            "OPENAI_API_KEY": "demo",
            "OPENAI_BASE_URL": "https://example.com/v1/",
            "OPENAI_MODEL_NAME": "demo-model",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["response"] == "OK"
    assert request_history[0][0] == "chat"
    assert request_history[0][1]["messages"][0]["content"] == settings.AI_TEST_PROMPT
    assert request_history[1][0] == "responses"
    assert request_history[1][1]["input"][0]["content"][0]["text"] == settings.AI_TEST_PROMPT


def _write_env(tmp_path, monkeypatch, lines):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    if lines is not None:
        env_file.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(env_manager, "env_file", env_file)
    return _build_settings_client()


def test_notification_settings_redact_webhook_secrets(tmp_path, monkeypatch):
    client = _write_env(
        tmp_path,
        monkeypatch,
        [
            "WEBHOOK_URL=https://hooks.example.com/notify?token=secret",
            'WEBHOOK_HEADERS={"Authorization":"Bearer secret"}',
            'WEBHOOK_BODY={"message":"{{content}}"}',
        ],
    )

    payload = client.get("/api/settings/notifications").json()

    assert payload["WEBHOOK_URL"] == ""
    assert payload["WEBHOOK_HEADERS"] == ""
    assert payload["WEBHOOK_URL_SET"] is True
    assert payload["WEBHOOK_HEADERS_SET"] is True
    assert payload["WEBHOOK_BODY"] == '{"message":"{{content}}"}'
    assert payload["CONFIGURED_CHANNELS"] == ["webhook"]
    assert not any(key.startswith(("NTFY", "TELEGRAM", "BARK")) for key in payload)


def test_update_notification_settings_rejects_invalid_webhook_config(tmp_path, monkeypatch):
    client = _write_env(tmp_path, monkeypatch, [])

    bad_url = client.put("/api/settings/notifications", json={"WEBHOOK_URL": "not-a-url"})
    assert bad_url.status_code == 422
    assert "WEBHOOK_URL" in bad_url.text

    orphan_body = client.put(
        "/api/settings/notifications",
        json={"WEBHOOK_BODY": '{"message":"{{content}}"}'},
    )
    assert orphan_body.status_code == 422

    ok = client.put(
        "/api/settings/notifications",
        json={"WEBHOOK_URL": "https://hooks.example.com/notify"},
    )
    assert ok.status_code == 200
    assert ok.json()["configured_channels"] == ["webhook"]


def test_system_status_reports_webhook_flag(tmp_path, monkeypatch):
    client = _write_env(
        tmp_path, monkeypatch, ["WEBHOOK_URL=https://hooks.example.com/notify"]
    )

    payload = client.get("/api/settings/status").json()

    assert payload["notification_configured"] is True
    assert payload["env_file"]["webhook_url_set"] is True
    assert payload["configured_notification_channels"] == ["webhook"]


def test_notification_test_endpoint_uses_stored_webhook_url(tmp_path, monkeypatch):
    client = _write_env(
        tmp_path, monkeypatch, ["WEBHOOK_URL=https://hooks.example.com/stored"]
    )
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

    def _fake_post(url, headers=None, json=None, data=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)

    response = client.post(
        "/api/settings/notifications/test",
        json={
            "channel": "webhook",
            "settings": {"WEBHOOK_BODY": '{"text":"{{title}}","url":"{{link}}"}'},
        },
    )

    assert response.status_code == 200
    assert response.json()["results"]["webhook"]["success"] is True
    assert captured["url"] == "https://hooks.example.com/stored"
    assert captured["json"]["url"] == "https://shopee.tw/"


def test_notification_test_endpoint_rejects_removed_channels(tmp_path, monkeypatch):
    client = _write_env(tmp_path, monkeypatch, [])

    response = client.post(
        "/api/settings/notifications/test",
        json={"channel": "telegram", "settings": {}},
    )

    assert response.status_code == 422
