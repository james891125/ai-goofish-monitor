"""
簡易網頁介面：只用標準函式庫的本機伺服器，不需要額外套件。

安全：只監聽 127.0.0.1；拒絕 Host 不是本機的請求（防 DNS rebinding）；
POST 一律要求 Content-Type: application/json（瀏覽器跨網站無法在沒有 CORS 的情況下送出）。
Cookie 與 API Key 只會寫入、不會回傳給網頁。
"""
import asyncio
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import envfile, service
from .ai import PROVIDERS
from .exporter import columns_for
from .login_state import LoginStateError
from .runner import AI_MODES, DETAIL_MODES, RunOptions

STATIC = Path(__file__).parent / "static" / "index.html"
PREVIEW_ROWS = 300
MAX_BODY = 2_000_000


class Job:
    """一次只允許一個搜尋工作；網頁用輪詢讀取進度。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.state = "idle"
        self.logs: list[str] = []
        self.error = ""
        self.summary: list[str] = []
        self.rows: list[dict] = []
        self.columns: list[str] = []
        self.count = 0
        self.csv_path: Path | None = None
        self.stop_event = threading.Event()

    def log(self, message: str) -> None:
        with self.lock:
            self.logs.append(message)
            self.logs = self.logs[-300:]

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "state": self.state,
                "log": list(self.logs),
                "error": self.error,
                "summary": list(self.summary),
                "columns": self.columns,
                "rows": self.rows,
                "count": self.count,
                "csv_ready": bool(self.csv_path and self.csv_path.exists()),
                "csv_name": self.csv_path.name if self.csv_path else "",
            }

    def start(self, options: RunOptions) -> None:
        with self.lock:
            if self.state == "running":
                raise RuntimeError("已有搜尋正在執行中。")
        self.reset()
        self.state = "running"
        threading.Thread(target=self._run, args=(options,), daemon=True).start()

    def _run(self, options: RunOptions) -> None:
        try:
            path, result = asyncio.run(
                service.run_job(options, log=self.log, should_stop=self.stop_event.is_set)
            )
            with self.lock:
                self.csv_path = path
                self.columns = columns_for(result.mode, result.rows)
                self.rows = [
                    {c: row.get(c, "") for c in self.columns} for row in result.rows[:PREVIEW_ROWS]
                ]
                self.count = len(result.rows)
                self.summary = result.summary
                self.state = "done"
        except Exception as exc:  # noqa: BLE001 - 顯示給使用者看
            with self.lock:
                self.error = str(exc)
                self.state = "error"
            self.log(f"[錯誤] {exc}")


JOB = Job()


def settings_payload() -> dict:
    settings = service.load_settings()
    return {
        "providers": {k: {"label": v[0], "base_url": v[1], "model": v[2]} for k, v in PROVIDERS.items()},
        "base_url": settings.base_url,
        "model": settings.model,
        "has_key": bool(settings.api_key),
        "webhook_set": bool(settings.webhook_url),
        "headless": settings.headless,
    }


def parse_options(data: dict) -> RunOptions:
    keywords = data.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.splitlines()
    detail = data.get("detail", "auto")
    ai = data.get("ai", "off")
    if detail not in DETAIL_MODES or ai not in AI_MODES:
        raise ValueError("補詳情或 AI 的選項不正確。")
    options = RunOptions(
        keywords=[str(k) for k in keywords],
        pages=int(data.get("pages") or 3),
        min_price=str(data.get("min_price") or "").strip(),
        max_price=str(data.get("max_price") or "").strip(),
        latest=bool(data.get("latest")),
        region=str(data.get("region") or "").strip(),
        free_shipping=bool(data.get("free_shipping")),
        detail=detail,
        ai=ai,
        title_match=bool(data.get("title_match", True)),
        exclude_accessories=bool(data.get("exclude_accessories", True)),
        extra_exclude=[str(data.get("extra_exclude") or "")],
    )
    options.validate()
    return options


class Handler(BaseHTTPRequestHandler):
    server_version = "ShopeeLite"

    def log_message(self, *args) -> None:  # 不在終端機洗版
        pass

    # --- helpers -------------------------------------------------------
    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in {"127.0.0.1", "localhost"}

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _read_json(self) -> dict | None:
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._error(415, "請求必須是 application/json")
            return None
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._error(413, "內容太大")
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._error(400, "不是有效的 JSON")
            return None
        return data if isinstance(data, dict) else {}

    # --- routes --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed_host():
            return self._error(403, "只接受本機連線")
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._json({"login": service.login_status(), "settings": settings_payload()})
        if path == "/api/job":
            return self._json(JOB.snapshot())
        if path == "/api/csv":
            if not (JOB.csv_path and JOB.csv_path.exists()):
                return self._error(404, "還沒有可下載的結果")
            return self._send(
                200,
                JOB.csv_path.read_bytes(),
                "text/csv; charset=utf-8",
                {"Content-Disposition": f'attachment; filename="{JOB.csv_path.name}"'},
            )
        self._error(404, "找不到")

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed_host():
            return self._error(403, "只接受本機連線")
        data = self._read_json()
        if data is None:
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/login":
                return self._json({"login": service.save_login(str(data.get("content") or ""))})
            if path == "/api/settings":
                return self._json(self._save_settings(data))
            if path == "/api/run":
                JOB.start(parse_options(data))
                return self._json({"started": True})
            if path == "/api/stop":
                JOB.stop_event.set()
                return self._json({"stopping": True})
            if path == "/api/webhook":
                if not (JOB.csv_path and JOB.csv_path.exists()):
                    return self._error(400, "還沒有可傳送的結果")
                return self._json({"message": service.send_webhook(JOB.csv_path)})
        except (LoginStateError, ValueError, RuntimeError) as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}: {exc}")
        self._error(404, "找不到")

    @staticmethod
    def _save_settings(data: dict) -> dict:
        updates: dict[str, str] = {}
        for field, key in (
            ("base_url", "OPENAI_BASE_URL"),
            ("model", "OPENAI_MODEL_NAME"),
        ):
            if data.get(field) is not None:
                updates[key] = str(data[field]).strip()
        # 金鑰與 Webhook 只在有輸入時才更新，留空代表沿用原值
        if str(data.get("api_key") or "").strip():
            updates["OPENAI_API_KEY"] = str(data["api_key"]).strip()
        if str(data.get("webhook_url") or "").strip():
            url = str(data["webhook_url"]).strip()
            if not url.lower().startswith(("http://", "https://")):
                raise ValueError("Webhook 網址必須以 http:// 或 https:// 開頭")
            updates["WEBHOOK_URL"] = url
        if data.get("clear_webhook"):
            updates["WEBHOOK_URL"] = ""
        if data.get("headless") is not None:
            updates["RUN_HEADLESS"] = "true" if data["headless"] else "false"
        if updates:
            envfile.write_env(updates)
        return {"settings": settings_payload()}


def serve(port: int = 8765, *, open_browser: bool = True) -> None:
    service.load_env()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"蝦皮商品清單介面已啟動：{url}（按 Ctrl+C 結束）")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已結束。")
    finally:
        server.server_close()
