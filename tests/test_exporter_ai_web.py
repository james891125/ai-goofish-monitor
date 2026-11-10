import asyncio
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from shopee_lite import envfile, exporter, service, web
from shopee_lite.ai import AIClient
from shopee_lite.browser import build_context_options, build_extra_headers, persist_session_cookies


def test_csv_has_bom_and_excel_friendly_columns():
    rows = [{"搜尋關鍵字": "mac mini", "品名": "Mac mini M4 16G/256G", "價格": 22000, "狀態": "全新"}]
    data = exporter.build_csv(rows)

    assert data.startswith(b"\xef\xbb\xbf")
    header = data.decode("utf-8-sig").splitlines()[0].split(",")
    assert header[:3] == ["搜尋關鍵字", "品名", "狀態"] and "價格" in header and "商品連結" in header
    assert "Mac mini M4 16G/256G" in data.decode("utf-8-sig")


def test_webhook_sends_csv_as_multipart_attachment(monkeypatch):
    calls = []

    class Resp:
        status_code = 204

        def raise_for_status(self):
            return None

    def fake_post(url, data=None, files=None, timeout=None, proxies=None):
        calls.append((url, data, files))
        return Resp()

    monkeypatch.setattr("shopee_lite.exporter.requests.post", fake_post)

    exporter.send_csv_webhook("https://discord.com/api/webhooks/1/abc", b"x", "a.csv", "清單")
    exporter.send_csv_webhook("https://hooks.example.com/in", b"x", "a.csv", "清單")

    assert "files[0]" in calls[0][2] and calls[0][2]["files[0]"][0] == "a.csv"
    assert "file" in calls[1][2] and calls[1][1]["content"] == "清單"
    with pytest.raises(ValueError):
        exporter.send_csv_webhook("ftp://nope", b"x", "a.csv", "m")


def test_ai_request_uses_max_completion_tokens_and_text_only(monkeypatch):
    seen = {}

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": '{"items":[{"id":0,"狀態":"二手"}]}'}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 15}}

    def fake_post(url, headers=None, json=None, timeout=None, proxies=None):
        seen.update(url=url, body=json, headers=headers)
        return Resp()

    monkeypatch.setattr("shopee_lite.ai.requests.post", fake_post)
    client = AIClient("https://api.example.com/v1/", "KEY", "model-x")

    result = asyncio.run(client.extract_batch([{"id": 0, "title": "Mac mini 二手", "desc": ""}]))

    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["body"]["max_completion_tokens"] == 4000 and "max_tokens" not in seen["body"]
    assert isinstance(seen["body"]["messages"][0]["content"], str)  # 純文字，沒有圖片
    assert result[0]["狀態"] == "二手" and client.usage.prompt_tokens == 120 and client.usage.estimated is False


def test_env_file_roundtrip_keeps_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# 說明\nOPENAI_API_KEY=\nKEEP=1\n", encoding="utf-8")
    envfile.write_env({"OPENAI_API_KEY": "sk-a b", "NEW": "x"}, path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 說明\nOPENAI_API_KEY=") and "KEEP=1" in text
    assert envfile.read_env(path)["OPENAI_API_KEY"] == "sk-a b"


def test_browser_helpers_drop_managed_headers_and_keep_other_cookie_fields(tmp_path):
    headers = build_extra_headers({"Accept": "*/*", "Cookie": "s=1", "Sec-Fetch-Mode": "cors", "sec-ch-ua": '"x"'})
    assert headers == {"sec-ch-ua": '"x"'}
    options = build_context_options({"headers": {"User-Agent": "UA", "Accept-Language": "zh-TW,zh;q=0.9"}})
    assert options["user_agent"] == "UA" and options["locale"] == "zh-TW"

    state = tmp_path / "s.json"
    snapshot = {"cookies": [], "env": {"a": 1}}
    fresh = [{"name": "SPC_EC", "value": "n", "domain": ".shopee.tw", "path": "/"},
             {"name": "o", "value": "x", "domain": ".example.com", "path": "/"}]
    assert persist_session_cookies(str(state), snapshot, fresh) is True
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert [c["name"] for c in saved["cookies"]] == ["SPC_EC"] and saved["env"] == {"a": 1}
    assert persist_session_cookies(str(state), snapshot, [fresh[1]]) is False


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(envfile, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(service, "STATE_FILE", tmp_path / "state" / "shopee.json")
    monkeypatch.setattr(service, "OUTPUT_DIR", tmp_path / "output")
    for key in ("OPENAI_API_KEY", "WEBHOOK_URL", "OPENAI_BASE_URL", "OPENAI_MODEL_NAME", "RUN_HEADLESS"):
        monkeypatch.delenv(key, raising=False)
    web.JOB.reset()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def call(port, method, path, body=None, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body).encode() if body is not None else None
    base = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=payload, headers={**base, **(headers or {})})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, raw


def test_web_serves_page_and_saves_cookie_without_echoing_secrets(server):
    status, page = call(server, "GET", "/")
    assert status == 200 and "蝦皮商品清單".encode() in page

    cookie = json.dumps({"cookies": [{"name": "SPC_EC", "value": "TOPSECRET", "domain": ".shopee.tw", "path": "/"}]})
    status, raw = call(server, "POST", "/api/login", {"content": cookie})
    assert status == 200 and json.loads(raw)["login"]["logged_in"] is True
    assert b"TOPSECRET" not in raw

    status, raw = call(server, "POST", "/api/settings", {"api_key": "sk-SECRETKEY", "webhook_url": "https://h.example/x", "model": "m1"})
    state = json.loads(raw)["settings"]
    assert status == 200 and state["has_key"] is True and state["webhook_set"] is True and state["model"] == "m1"
    assert b"sk-SECRETKEY" not in raw and b"h.example" not in raw
    status, raw = call(server, "GET", "/api/state")
    assert b"sk-SECRETKEY" not in raw and b"TOPSECRET" not in raw

    status, raw = call(server, "POST", "/api/login", {"content": "不是 JSON"})
    assert status == 400 and "error" in json.loads(raw)


def test_web_rejects_foreign_hosts_and_non_json_posts(server):
    assert call(server, "GET", "/api/state", headers={"Host": "evil.example.com"})[0] == 403
    assert call(server, "POST", "/api/run", None)[0] == 415
    conn = HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("POST", "/api/run", body="keywords=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert conn.getresponse().status == 415
    status, raw = call(server, "POST", "/api/run", {"keywords": "", "detail": "auto", "ai": "off"})
    assert status == 400 and "關鍵字" in json.loads(raw)["error"]
    status, raw = call(server, "POST", "/api/run", {"keywords": "x", "detail": "bogus"})
    assert status == 400
