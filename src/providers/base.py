"""A provider must prove access/capabilities, not infer authorization from cookies."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from src.domain.models.shopee import Product, ShopeeTask


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code, self.public_message, self.retry_after = code, message, retry_after


@dataclass(frozen=True)
class ProviderCapabilities:
    keyword: bool = True
    price: bool = True
    category: bool = True
    condition: bool = True
    region: bool = True
    seller_type: bool = True
    ads: bool = True


class ProductProvider(ABC):
    id: str
    name: str
    capabilities = ProviderCapabilities()
    available = True
    authorization_status = 'not_required'

    def status(self):
        return dict(id=self.id, name=self.name, available=self.available,
                    authorization_status=self.authorization_status, expires_at=None,
                    capabilities=asdict(self.capabilities))

    @abstractmethod
    async def search(self, task: ShopeeTask) -> list[Product]:
        """Return only legitimately available data, raising a typed safe error."""
