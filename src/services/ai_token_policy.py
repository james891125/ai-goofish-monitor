"""以固定欄位、明確預算與無機密指紋減少重複 AI 分析。"""
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.ai_message_builder import build_analysis_text_prompt

# Bump when evidence/validation semantics change, so previous judgments are not reused.
ANALYSIS_POLICY_VERSION = 'shopee-tw-analysis-v2'
DEFAULT_MAX_OUTPUT_TOKENS = 1200
DEFAULT_DESCRIPTION_CHARS = 2000
DEFAULT_MAX_IMAGES = 2
DEFAULT_MAX_PROMPT_CHARS = 12000
DECISION_FIELDS = (
    'decision_mode', 'keyword', 'description', 'custom_prompt', 'analyze_images',
    'min_price', 'max_price', 'category', 'condition', 'region', 'seller_type',
    'exclude_keywords', 'exclude_ads',
)


def project_product(product: dict, description_chars: int = DEFAULT_DESCRIPTION_CHARS) -> dict:
    """只傳送判斷所需欄位；保留 null，不傳時間戳、連結或未授權圖片。"""
    limit = max(256, min(int(description_chars), 4000))
    description = str(product.get('description') or '')
    seller = product.get('seller') or {}
    if not isinstance(seller, dict):
        seller = {}

    def bounded(value, size):
        return value[:size] if isinstance(value, str) else None

    return {
        'platform': product.get('platform', 'shopee_tw'),
        'product_id': bounded(product.get('product_id'), 120),
        'title': bounded(product.get('title'), 500),
        'price_twd': product.get('price_twd'),
        'original_price_twd': product.get('original_price_twd'),
        'condition': product.get('condition'),
        'description': description[:limit],
        'description_truncated': len(description) > limit or product.get('description_truncated') is True,
        'category': bounded(product.get('category'), 160),
        'is_ad': product.get('is_ad'),
        'data_source': bounded(product.get('data_source'), 80),
        'data_quality': product.get('data_quality'),
        'seller': {
            'rating': seller.get('rating'),
            'review_count': seller.get('review_count'),
            'location': bounded(seller.get('location'), 160),
            'seller_type': seller.get('seller_type'),
            'verified_type': bounded(seller.get('verified_type'), 80),
        },
        'images': [],
    }


def _endpoint_identity(base_url: str) -> str:
    """端點只用於指紋，不保存帳密、token 或常見驗證查詢參數。"""
    try:
        parsed = urlsplit(base_url.strip())
        # Avoid credentials in netloc. API/version query options still invalidate.
        host = (parsed.hostname or '').lower()
        if ':' in host:
            host = '[' + host + ']'
        netloc = host + (f':{parsed.port}' if parsed.port is not None else '')
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if not any(word in key.lower() for word in (
                     'key', 'token', 'secret', 'password', 'signature', 'auth', 'credential',
                 ))]
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip('/'), urlencode(sorted(query)), ''))
    except ValueError:
        return ''


def analysis_cache_key(task, product, prompt: str, settings, image_urls: list[str]) -> str:
    """持久化只保存 SHA-256，不序列化整個設定或任何 API Key。"""
    stable_product = product.model_dump(mode='json', exclude={'collected_at', 'product_url'})
    # Hash complete original description, even when only its bounded prefix is sent.
    # A change beyond that prefix must not silently reuse an older recommendation.
    payload = {
        'policy': ANALYSIS_POLICY_VERSION,
        'product': stable_product,
        'criteria': {field: getattr(task, field) for field in DECISION_FIELDS},
        'prompt': prompt,
        'message_contract': build_analysis_text_prompt('', '', include_images=bool(image_urls)),
        'images': image_urls,
        'settings': {
            'model': getattr(settings, 'model_name', ''),
            'endpoint': _endpoint_identity(getattr(settings, 'base_url', '')),
            'json_output': getattr(settings, 'enable_response_format', True),
            'max_output_tokens': getattr(settings, 'max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS),
            'description_chars': getattr(settings, 'product_description_chars', DEFAULT_DESCRIPTION_CHARS),
            'max_images': getattr(settings, 'max_images', DEFAULT_MAX_IMAGES),
            'max_prompt_chars': getattr(settings, 'max_prompt_chars', DEFAULT_MAX_PROMPT_CHARS),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()
