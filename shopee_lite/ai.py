"""
選用的 AI 整理：把一批商品文字交給模型，補出規則抓不到的欄位。

- 只送文字（標題＋描述摘要），不送圖片
- 每次請求放 BATCH_SIZE 件商品，一次回傳整張表，所以用量遠少於「一件一次」
- 走 OpenAI 相容的 Chat Completions（Gemini / OpenRouter / OpenAI 都可），使用 max_completion_tokens
- 模型只被要求「文字裡有寫才填」，找不到就留空
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from .extract import CONDITIONS, FIELDS

BATCH_SIZE = 20
DESCRIPTION_CHARS = 300
MAX_COMPLETION_TOKENS = 4000

PROVIDERS = {
    "gemini": ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "google/gemini-2.5-flash"),
    "openai": ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
}

PROMPT = """你是商品資料整理員。下面是蝦皮商品清單（JSON 陣列，每件有 id、title、desc）。
請只根據文字內容，為每一件填入下列欄位；文字裡沒有明確寫出的就填空字串，不要猜測：

- 狀態：只能是 全新、近全新、二手、福利品、展示機、故障/零件機、預購 其中之一，或空字串
- 規格：這件商品最關鍵的型號規格，用頓號分隔的短詞，例如 M4 Pro、46mm、GPS；或 RTX 5070 Ti；不要重複記憶體與容量
- 記憶體：例如 16GB（電腦或手機的記憶體；顯示卡則填顯存）
- 儲存容量：例如 512GB、1TB
- 保固：用一短句，例如 保固至 2027/08、原廠保固中、已過保/無保固、保固 1 年

只輸出 JSON，格式：{"items":[{"id":0,"狀態":"","規格":"","記憶體":"","儲存容量":"","保固":""}]}

商品清單：
"""


@dataclass
class AIUsage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False

    def summary(self) -> str:
        if not self.requests:
            return "AI 未被呼叫"
        tokens = f"約 {self.prompt_tokens + self.completion_tokens} tokens"
        mark = "（估算）" if self.estimated else ""
        return f"AI 共 {self.requests} 次請求，{tokens}{mark}"


@dataclass
class AIClient:
    base_url: str
    api_key: str
    model: str
    proxy: str = ""
    usage: AIUsage = field(default_factory=AIUsage)

    def is_ready(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def _post(self, prompt: str) -> dict:
        url = self.base_url.rstrip("/") + "/chat/completions"
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": MAX_COMPLETION_TOKENS,
            },
            timeout=120,
            proxies=proxies,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"AI 服務回應 {response.status_code}: {response.text[:200]}")
        return response.json()

    async def extract_batch(self, items: list[dict]) -> dict[int, dict]:
        """items: [{"id":int,"title":str,"desc":str}]；回傳 {id: {欄位: 值}}。失敗時拋出例外。"""
        prompt = PROMPT + json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        data = await asyncio.to_thread(self._post, prompt)
        self.usage.requests += 1
        usage = data.get("usage") or {}
        if usage.get("prompt_tokens") is not None:
            self.usage.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.usage.completion_tokens += int(usage.get("completion_tokens") or 0)
        else:
            self.usage.estimated = True
            self.usage.prompt_tokens += len(prompt)
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if usage.get("prompt_tokens") is None:
            self.usage.completion_tokens += len(content)
        return parse_ai_reply(content)


def parse_ai_reply(content: str) -> dict[int, dict]:
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 回覆不是 JSON")
    payload = json.loads(text[start:end + 1])
    result: dict[int, dict] = {}
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        try:
            item_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        result[item_id] = clean_fields(entry)
    return result


def clean_fields(entry: dict) -> dict:
    cleaned = {}
    for name in FIELDS:
        value = entry.get(name)
        value = "" if value is None else str(value).strip()
        if name == "狀態" and value not in CONDITIONS:
            value = ""
        cleaned[name] = value
    return cleaned


def build_batch(rows: list[dict], start: int) -> list[dict]:
    return [
        {
            "id": start + offset,
            "title": row["品名"],
            "desc": (row.get("_描述") or "")[:DESCRIPTION_CHARS],
        }
        for offset, row in enumerate(rows)
    ]


async def enrich_rows(
    client: AIClient,
    rows: list[dict],
    log: Callable[[str], None],
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    """替每一列加上 row["_AI"]（欄位字典）。單一批次失敗只記錄，不中斷整個流程。"""
    for start in range(0, len(rows), BATCH_SIZE):
        if should_stop and should_stop():
            return
        chunk = rows[start:start + BATCH_SIZE]
        log(f"AI 整理第 {start + 1}–{start + len(chunk)} 件商品...")
        try:
            result = await client.extract_batch(build_batch(chunk, start))
        except Exception as exc:  # noqa: BLE001 - 單批失敗不影響其他批次
            log(f"AI 這一批失敗，改用規則結果: {exc}")
            continue
        for offset, row in enumerate(chunk):
            row["_AI"] = result.get(start + offset)
