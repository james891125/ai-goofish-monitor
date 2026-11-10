"""Shopee Taiwan's source-neutral, evidence-preserving domain contracts."""
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.core.cron_utils import validate_cron_expression


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Seller(BaseModel):
    model_config = ConfigDict(extra='forbid')
    seller_id: str | None = None
    name: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    location: str | None = None
    verified_type: str | None = None
    seller_type: Literal['personal', 'business'] | None = None


class Product(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    platform: Literal['shopee_tw'] = 'shopee_tw'
    product_id: str = Field(min_length=1, max_length=120, pattern=r'^[\w.-]+$')
    title: str = Field(min_length=1, max_length=500)
    price_twd: float = Field(ge=0, le=1_000_000_000)
    original_price_twd: float | None = Field(default=None, ge=0)
    condition: Literal['new', 'used'] | None = None
    description: str = Field(default='', max_length=20000)
    images: list[str] = Field(default_factory=list, max_length=10)
    images_allowed: bool = False
    product_url: str = ''
    seller: Seller = Field(default_factory=Seller)
    listed_at: datetime | None = None
    collected_at: str = Field(default_factory=utc_now)
    data_source: str = ''
    data_quality: Literal['partial', 'complete', 'mock'] = 'partial'
    category: str | None = None
    is_ad: bool | None = None

    @field_validator('product_url')
    @classmethod
    def valid_product_url(cls, value):
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme != 'https' or parsed.hostname not in {'shopee.tw', 'www.shopee.tw'} or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise ValueError('商品連結必須是 https://shopee.tw 的網址')
        return value

    @field_validator('images')
    @classmethod
    def valid_image_urls(cls, values):
        # Images are never fetched by the server; only approved public Shopee CDN URLs.
        for value in values:
            parsed = urlparse(value)
            host = parsed.hostname or ''
            if parsed.scheme != 'https' or not (host.endswith('.susercontent.com') or host.endswith('.shopee.tw')) or parsed.username or parsed.password or parsed.port not in {None, 443}:
                raise ValueError('圖片只接受 HTTPS 蝦皮公開 CDN 網址')
        return values


class ShopeeTask(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: int | None = None
    task_name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    keyword: str = Field(min_length=1, max_length=200)
    provider: Literal['mock', 'import', 'shopee', 'browser_experiment'] = 'mock'
    decision_mode: Literal['keyword', 'ai'] = 'keyword'
    description: str = Field(default='', max_length=10000)
    analyze_images: bool = False
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    max_items: int = Field(default=50, ge=1, le=500)
    max_pages: int = Field(default=3, ge=1, le=20)
    category: str | None = None
    condition: Literal['new', 'used'] | None = None
    region: str | None = None
    seller_type: Literal['personal', 'business'] | None = None
    exclude_keywords: list[str] = Field(default_factory=list, max_length=100)
    exclude_ads: bool = False
    cron: str | None = None
    notify: Literal['recommended', 'all'] = 'recommended'
    notify_price_drop: bool = False
    custom_prompt: str = Field(default='', max_length=30000)

    @field_validator('cron')
    @classmethod
    def valid_cron(cls, value):
        return validate_cron_expression(value)

    @field_validator('task_name', 'keyword')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不得空白')
        return value.strip()

    @model_validator(mode='after')
    def valid_task(self):
        if self.provider == 'browser_experiment':
            if self.decision_mode != 'ai':
                raise ValueError('實驗瀏覽快照必須使用 AI 分析，不會以關鍵字結果代替 AI 判斷')
            if self.cron:
                raise ValueError('實驗瀏覽快照僅供手動分析，不支援排程或自動開啟瀏覽器')
            if self.max_items > 5 or self.max_pages != 1:
                raise ValueError('實驗瀏覽快照每次最多 5 件，頁數必須為 1')
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError('最低價格不得大於最高價格')
        if self.decision_mode == 'ai' and not self.description.strip():
            raise ValueError('AI 分析模式必須填寫詳細需求')
        return self
