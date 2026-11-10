"""Offline snapshots and a fail-closed official authorization boundary.

The optional local browser experiment is separate from this server and never
starts from a provider search or a scheduler job.
"""
from src.providers.base import ProductProvider, ProviderError, ProviderCapabilities
from src.services.product_normalizer import normalize_product, filter_products

MOCK_PRODUCTS = [
    dict(product_id='mock-rtx-5070ti', title='【模擬】RTX 5070 Ti 16GB 二手顯示卡', price_twd=20000,
         description='合成測試資料，並非真實販售商品或市場行情。保固資訊不足。', condition='used',
         category='電腦零組件', seller=dict(name='模擬賣家', location='臺北市', seller_type='personal'), is_ad=False),
    dict(product_id='mock-mac-mini-m4', title='【模擬】Mac mini M4 16GB 256GB', price_twd=15000,
         description='合成測試資料，並非真實販售商品或市場行情。維修與保固資訊不足。', condition='used',
         category='電腦', is_ad=False),
    dict(product_id='mock-mac-box', title='【模擬】Mac mini M4 空盒', price_twd=500,
         description='只有空盒，排除關鍵字測試。', is_ad=False),
]


class MockProvider(ProductProvider):
    id, name = 'mock', '模擬資料（非真實商品）'

    async def search(self, task):
        return filter_products([normalize_product(row, self.id) for row in MOCK_PRODUCTS], task)


class ImportProvider(ProductProvider):
    id, name = 'import', '合法匯入資料'

    def __init__(self, repository):
        self.repository = repository

    async def search(self, task):
        return filter_products([normalize_product(row, self.id) for row in self.repository.imported_products()], task)


class ShopeeProvider(ProductProvider):
    id, name = 'shopee', '蝦皮授權資料來源（尚未啟用）'
    available = False
    authorization_status = 'waiting_authorization'
    capabilities = ProviderCapabilities(False, False, False, False, False, False, False)

    async def search(self, task):
        raise ProviderError('authorization_required', '等待資料來源授權：尚未驗證可用的全站關鍵字搜尋權限。')


class BrowserSnapshotProvider(ProductProvider):
    id, name = 'browser_experiment', '實驗瀏覽快照（手動更新）'
    authorization_status = 'experimental_unverified'
    capabilities = ProviderCapabilities(True, True, False, False, False, False, False)

    def __init__(self, repository):
        self.repository = repository

    def status(self):
        return dict(super().status(), live_search=False, manual_only=True,
                    warning='非官方授權來源。僅分析已匯入快照，不會重新瀏覽或自動搜尋蝦皮。')

    async def search(self, task):
        if task.cron or task.max_items > 5 or task.max_pages != 1:
            raise ProviderError('browser_snapshot_limits', '實驗瀏覽快照僅供手動分析，每次最多 5 件，不支援排程。')
        return filter_products([normalize_product(row, self.id) for row in self.repository.browser_snapshots()], task)


def build_providers(repository):
    return {provider.id: provider for provider in [MockProvider(), ImportProvider(repository), ShopeeProvider(), BrowserSnapshotProvider(repository)]}
