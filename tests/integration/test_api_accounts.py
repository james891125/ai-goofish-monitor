import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import accounts
from src.infrastructure.config.env_manager import env_manager


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(env_manager, "env_file", tmp_path / ".env")
    monkeypatch.setenv("ACCOUNT_STATE_DIR", str(tmp_path / "state"))
    app = FastAPI()
    app.include_router(accounts.router)
    return TestClient(app)


def _cookie(name, value, **extra):
    return {"name": name, "value": value, "domain": ".shopee.tw", "path": "/", **extra}


def _logged_in_snapshot() -> str:
    return json.dumps(
        {
            "cookies": [
                _cookie("SPC_EC", "secret-token", expires=4102444800, sameSite="no_restriction"),
                _cookie("SPC_U", "123456"),
                _cookie("SPC_F", "device"),
            ],
            "env": {"navigator": {"userAgent": "UA"}},
        }
    )


def test_paste_cookie_saves_default_account_and_reports_login(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/accounts", json={"content": _logged_in_snapshot()})

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "shopee"
    assert payload["logged_in"] is True
    assert payload["shopee_user_id"] == "123456"
    assert payload["cookie_count"] == 3
    assert payload["expired"] is False
    assert "secret-token" not in response.text

    saved = json.loads((tmp_path / "state" / "shopee.json").read_text(encoding="utf-8"))
    assert saved["cookies"][0]["sameSite"] == "None"
    assert saved["env"]["navigator"]["userAgent"] == "UA"

    listed = client.get("/api/accounts").json()
    assert [item["name"] for item in listed] == ["shopee"]
    assert listed[0]["logged_in"] is True and listed[0]["updated_at"]


def test_paste_again_requires_overwrite_flag(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = {"content": _logged_in_snapshot()}
    assert client.post("/api/accounts", json=body).status_code == 200
    assert client.post("/api/accounts", json=body).status_code == 409

    response = client.post("/api/accounts", json={**body, "overwrite": True})
    assert response.status_code == 200
    assert response.json()["message"] == "帳號已更新"


def test_plain_cookie_array_is_accepted_but_flagged_when_not_logged_in(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    content = json.dumps([_cookie("SPC_F", "device", expirationDate=4102444800)])

    payload = client.post("/api/accounts", json={"name": "guest", "content": content}).json()

    assert payload["logged_in"] is False
    saved = json.loads((tmp_path / "state" / "guest.json").read_text(encoding="utf-8"))
    assert saved["cookies"][0]["expires"] == 4102444800.0
    assert saved["origins"] == []


def test_rejects_content_that_is_not_shopee_login_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    not_json = client.post("/api/accounts", json={"content": "hello"})
    other_site = client.post(
        "/api/accounts",
        json={"content": json.dumps({"cookies": [{"name": "a", "value": "b", "domain": ".example.com"}]})},
    )
    no_cookies = client.post("/api/accounts", json={"content": "{}"})

    assert not_json.status_code == 400
    assert other_site.status_code == 400 and "蝦皮" in other_site.json()["detail"]
    assert no_cookies.status_code == 400
    assert not (tmp_path / "state").exists()
