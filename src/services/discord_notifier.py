"""Discord webhook adapter for normalized Shopee products.

No scraping or image download occurs here. The caller owns notification policy,
source/media permissions and persistent deduplication, and records success only
when ``send`` returns True. Timeouts are not retried: delivery may be uncertain.
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
import re
from urllib.parse import urlsplit

import httpx

from src.services.remote_image_urls import safe_public_https_url

logger = logging.getLogger(__name__)
_WEBHOOK_PATH = re.compile(r"/api/(?:v\d+/)?webhooks/\d{1,24}/[A-Za-z0-9._-]{20,256}/?\Z")
_WEBHOOK_IN_LOG = re.compile(r"https://(?:discord\.com|discordapp\.com)(?::443)?/api/(?:v\d+/)?webhooks/[^\s'\"<>]+", re.I)


class _WebhookLogRedactor(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = _WEBHOOK_IN_LOG.sub("https://discord.com/api/webhooks/[REDACTED]", message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


# httpx emits full request URLs at INFO, including the webhook credential. Do not
# rely on deployment log levels to keep that credential private.
if not any(isinstance(item, _WebhookLogRedactor) for item in logging.getLogger("httpx").filters):
    logging.getLogger("httpx").addFilter(_WebhookLogRedactor())


def validate_discord_webhook_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 33 or c == "\\" for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname in {"discord.com", "discordapp.com"}
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.query and not parsed.fragment
            and _WEBHOOK_PATH.fullmatch(parsed.path)
        )
    except ValueError:
        return False


def _text(value: object, limit: int, fallback: str = "資訊不足") -> str:
    text = str(value).strip() if value is not None else ""
    return (text or fallback)[:limit]


def _price(value: object) -> str:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return "價格資訊不足"
        return f"NT${amount:,.0f}" if amount == amount.to_integral_value() else f"NT${amount:,.2f}"
    except (InvalidOperation, ValueError):
        return "價格資訊不足"


def build_discord_payload(product: dict, analysis: dict) -> dict:
    """Render one embed below Discord limits; disable all user/role mentions."""
    recommended = analysis.get("is_recommended", analysis.get("recommended"))
    verdict = "值得考慮" if recommended is True else "不推薦" if recommended is False else "資訊不足"
    if analysis.get('mode') == 'keyword':
        verdict = '符合關鍵字條件；未進行 AI 分析'
    risks = analysis.get("risk_tags", analysis.get("risks", []))
    risk_text = "、".join(str(tag) for tag in risks) if isinstance(risks, list) and risks else "未列出已知風險（不代表無風險）"
    embed = {
        "title": _text(product.get("title"), 256, "蝦皮商品"),
        "description": _text(analysis.get("reason"), 1800),
        "color": 0x238636 if recommended is True else 0xE87722,
        "fields": [
            {"name": "商品價格", "value": _price(product.get("price_twd")), "inline": True},
            {"name": "關鍵字篩選" if analysis.get("mode") == "keyword" else "AI 推薦", "value": verdict, "inline": True},
            {"name": "主要風險", "value": _text(risk_text, 900), "inline": False},
            {"name": "發現時間", "value": _text(product.get("collected_at"), 100), "inline": False},
        ],
        "footer": {"text": "臺灣蝦皮 AI 商品監控 · 分析僅供參考，交易前請自行確認"},
    }
    # Product destinations must remain on Shopee Taiwan, never an imported
    # arbitrary phishing URL. No redirect or abbreviated link is generated.
    product_url = safe_public_https_url(product.get("product_url"))
    if product_url and urlsplit(product_url).hostname in {"shopee.tw", "www.shopee.tw"}:
        embed["url"] = product_url
        embed["fields"].append({"name": "商品原始連結", "value": product_url[:1024], "inline": False})
    images = product.get("images") or []
    # Importers/providers can explicitly disallow redistributing media.
    if product.get("images_allowed", True) and isinstance(images, list):
        for candidate in images:
            image_url = safe_public_https_url(candidate)
            if image_url:
                embed["thumbnail"] = {"url": image_url}
                break
    try:
        discovered = datetime.fromisoformat(str(product.get("collected_at", "")).replace("Z", "+00:00"))
        if discovered.tzinfo is not None:
            embed["timestamp"] = discovered.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return {"allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False}, "embeds": [embed]}


async def send(product: dict, analysis: dict, webhook_url: str) -> bool:
    """POST to a validated Discord webhook, retrying only one explicit short 429.

    Redirects are refused. No URL, response body or exception detail is logged,
    because any of those can contain the webhook credential.
    """
    if not validate_discord_webhook_url(webhook_url):
        logger.warning("Discord Webhook 網址格式無效，未傳送通知")
        return False
    payload = build_discord_payload(product, analysis)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False) as client:
            for attempt in range(2):
                response = await client.post(webhook_url, json=payload)
                if response.status_code in (200, 204):
                    return True
                if response.status_code == 429 and attempt == 0:
                    try:
                        delay = float(response.json().get("retry_after", response.headers.get("Retry-After", 1)))
                    except (ValueError, TypeError, AttributeError):
                        return False
                    if 0 <= delay <= 5:
                        await asyncio.sleep(delay)
                        continue
                logger.warning("Discord 通知未成功，HTTP 狀態 %d", response.status_code)
                return False
    except (httpx.HTTPError, ValueError):
        logger.warning("Discord 通知連線失敗或逾時；未自動重送")
    return False
