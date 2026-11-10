"""Normalize explicitly supplied TWD data, without guessing private API units."""
from src.domain.models.shopee import Product, ShopeeTask, utc_now


def normalize_product(raw: dict, source: str = 'import') -> Product:
    data = dict(raw)
    data['data_source'] = source
    data['collected_at'] = utc_now()
    data['data_quality'] = 'mock' if source == 'mock' else 'partial'
    if data.get('seller') is None:
        data['seller'] = {}
    return Product.model_validate(data)


def filter_products(products: list[Product], task: ShopeeTask) -> list[Product]:
    result, seen = [], set()
    terms = task.keyword.casefold().split()
    for product in products:
        text = f'{product.title} {product.description}'.casefold()
        if not all(term in text for term in terms):
            continue
        if any(term.strip().casefold() in text for term in task.exclude_keywords if term.strip()):
            continue
        if task.min_price is not None and product.price_twd < task.min_price:
            continue
        if task.max_price is not None and product.price_twd > task.max_price:
            continue
        # Unknown evidence cannot satisfy a requested filter.
        if task.category and product.category != task.category:
            continue
        if task.condition and product.condition != task.condition:
            continue
        if task.region and product.seller.location != task.region:
            continue
        if task.seller_type and product.seller.seller_type != task.seller_type:
            continue
        if task.exclude_ads and product.is_ad is not False:
            continue
        if product.product_id in seen:
            continue
        seen.add(product.product_id)
        result.append(product)
        if len(result) >= min(task.max_items, task.max_pages * 50):
            break
    return result
