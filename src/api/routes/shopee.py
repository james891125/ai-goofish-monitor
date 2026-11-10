"""Authenticated Shopee-only HTTP surface. Providers never expose credentials."""
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from src.domain.models.shopee import ShopeeTask
from src.providers.base import ProviderError
from src.services.product_normalizer import normalize_product
from src.infrastructure.config.env_manager import env_manager

router=APIRouter(prefix='/api/shopee',tags=['shopee_tw'])


def runtime(request): return request.app.state.runtime


@router.get('/status')
async def status(request: Request):
    return dict(release_status='waiting_authorization',message='等待資料來源授權。模擬與匯入可測試，尚未提供全站自動搜尋。',
                providers=[provider.status() for provider in runtime(request).monitor.providers.values()],
                ai_configured=all(os.getenv(key) for key in ['OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_MODEL_NAME']),
                discord_configured=bool(os.getenv('DISCORD_WEBHOOK_URL')),timezone='Asia/Taipei')


@router.get('/tasks')
async def list_tasks(request: Request):
    rt=runtime(request)
    return [rt.task_payload(task) for task in rt.repository.tasks()]


@router.post('/tasks',status_code=201)
async def create_task(payload: ShopeeTask, request: Request):
    rt=runtime(request)
    task=rt.repository.save_task(payload)
    rt.reload()
    return rt.task_payload(task)


@router.put('/tasks/{task_id}')
async def update_task(task_id: int,payload: ShopeeTask,request: Request):
    rt=runtime(request)
    if task_id in rt.jobs: raise HTTPException(409,'請等候任務結束後再修改。')
    try: task=rt.repository.save_task(payload,task_id)
    except KeyError: raise HTTPException(404,'找不到任務。')
    rt.reload()
    return rt.task_payload(task)


@router.delete('/tasks/{task_id}')
async def delete_task(task_id: int,request: Request):
    rt=runtime(request)
    if task_id in rt.jobs: raise HTTPException(409,'請等候任務結束後再刪除。')
    if not rt.repository.delete_task(task_id): raise HTTPException(404,'找不到任務。')
    rt.reload()
    return {'deleted':True,'history_preserved':True}


@router.post('/tasks/{task_id}/run',status_code=202)
async def run_task(task_id: int,request: Request):
    try: await runtime(request).start_task(task_id)
    except ProviderError as exc: raise HTTPException(404 if exc.code=='not_found' else 409,exc.public_message)
    return {'status':'started','task_id':task_id}


@router.get('/products')
async def products(request: Request,task_id: int | None=None):
    return runtime(request).repository.products(task_id)


@router.get('/products/{product_id}/history')
async def history(product_id: str,request: Request,task_id: int | None=None,source: str | None=None):
    return runtime(request).repository.history(product_id,task_id,source)


@router.get('/runs')
async def runs(request: Request,task_id: int | None=None):
    return runtime(request).repository.runs(task_id)


class ImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    products: list[dict]=Field(min_length=1,max_length=500)
    rights_confirmed: bool=False


@router.post('/import')
async def import_products(payload: ImportRequest,request: Request):
    if not payload.rights_confirmed:
        raise HTTPException(422,'請確認有權匯入、保存及分析這些資料。')
    try: normalized=[normalize_product(row,'import') for row in payload.products]
    except (ValueError,TypeError):
        raise HTTPException(422,'商品資料格式錯誤：請使用文件中的標準格式，金額為新臺幣。')
    return {'imported':runtime(request).repository.import_products(normalized)}


class BrowserImportRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    products: list[dict]=Field(min_length=1,max_length=5)
    rights_confirmed: bool=False
    risk_confirmed: bool=False


@router.post('/browser-import')
async def import_browser_snapshots(payload: BrowserImportRequest,request: Request):
    if not payload.rights_confirmed or not payload.risk_confirmed:
        raise HTTPException(422,'請分別確認資料使用權及實驗瀏覽的平台條款、帳號限制風險。')
    try:
        normalized=[normalize_product(row,'browser_experiment') for row in payload.products]
        # The experimental collector has no image permission or seller-history access.
        if any(product.images or product.images_allowed for product in normalized):
            raise ValueError('Images are not supported in this experiment')
    except (ValueError,TypeError):
        raise HTTPException(422,'實驗快照格式錯誤：最多 5 件、明確新臺幣價格、含時區的原始採集時間，且不包含圖片。')
    return {'imported':runtime(request).repository.import_browser_snapshots(normalized)}


class SettingsUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    OPENAI_API_KEY: str | None=Field(default=None,max_length=1000)
    OPENAI_BASE_URL: str | None=Field(default=None,max_length=1000)
    OPENAI_MODEL_NAME: str | None=Field(default=None,max_length=200)
    DISCORD_WEBHOOK_URL: str | None=Field(default=None,max_length=1000)


@router.get('/settings')
async def get_settings():
    return dict(OPENAI_BASE_URL=os.getenv('OPENAI_BASE_URL',''),OPENAI_MODEL_NAME=os.getenv('OPENAI_MODEL_NAME',''),
                ai_configured=all(os.getenv(key) for key in ['OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_MODEL_NAME']),
                discord_configured=bool(os.getenv('DISCORD_WEBHOOK_URL')))


@router.put('/settings')
async def update_settings(payload: SettingsUpdate):
    updates=payload.model_dump(exclude_none=True)
    try:
        for value in updates.values(): value.encode('utf-8',errors='strict')
    except UnicodeError:
        raise HTTPException(422,'設定包含無效的 Unicode 字元。')
    if any('\n' in value or '\r' in value or '\x00' in value for value in updates.values()):
        raise HTTPException(422,'設定不可包含換行或控制字元。')
    if updates.get('DISCORD_WEBHOOK_URL'):
        from src.services.discord_notifier import validate_discord_webhook_url
        try:
            if validate_discord_webhook_url(updates['DISCORD_WEBHOOK_URL']) is False:
                raise ValueError()
        except ValueError: raise HTTPException(422,'Discord Webhook 網址格式無效。')
    if updates.get('OPENAI_BASE_URL'):
        from urllib.parse import urlparse
        parsed=urlparse(updates['OPENAI_BASE_URL'])
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422,'AI Base URL 必須是有效的 HTTP(S) 網址。')
    if not env_manager.update_values(updates):
        raise HTTPException(500,'無法儲存設定。')
    os.environ.update(updates)
    return {'saved':True}
