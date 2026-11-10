import asyncio
import sqlite3
import httpx
import pytest
from src.domain.models.shopee import ShopeeTask,Product
from src.infrastructure.persistence.shopee_repository import ShopeeRepository
from src.providers.shopee import MockProvider,ShopeeProvider,ImportProvider
from src.providers.base import ProviderError
from src.services.product_normalizer import normalize_product,filter_products
from src.services.product_monitor import ProductMonitor
from src.services.shopee_runtime import ShopeeRuntime


@pytest.fixture
def repo(tmp_path): return ShopeeRepository(str(tmp_path/'app.sqlite3'))


def product(**kwargs):
    return normalize_product(dict(product_id='item-1',title='RTX 5070 Ti',price_twd=20000,**kwargs))


def task(repo,**kwargs):
    return repo.save_task(ShopeeTask(task_name='RTX',keyword='RTX 5070 Ti',**kwargs))


def test_migration_preserves_existing_tables_and_is_idempotent(tmp_path):
    path=str(tmp_path/'old.sqlite3')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE user_private_history (value TEXT)')
        conn.execute("INSERT INTO user_private_history VALUES ('preserve')")
    ShopeeRepository(path); ShopeeRepository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT value FROM user_private_history').fetchone()==('preserve',)
        assert conn.execute("SELECT COUNT(*) FROM app_metadata WHERE key='migration:shopee_tw_v1'").fetchone()==(1,)


def test_normalization_does_not_invent_seller_evidence():
    p=product(seller=None)
    assert p.seller.rating is None and p.seller.seller_type is None
    assert p.data_quality=='partial' and p.platform=='shopee_tw'
    with pytest.raises(ValueError): product(product_url='javascript:alert(1)')
    with pytest.raises(ValueError): normalize_product({'product_id':'1','title':'test','price_twd':float('nan')})


def test_keywords_filters_limits_and_unknown_fields(repo):
    p=product(condition='used',category='顯示卡',is_ad=False,seller={'location':'臺北市','seller_type':'personal'})
    base=task(repo,min_price=15000,max_price=25000,condition='used',region='臺北市',seller_type='personal',exclude_ads=True,category='顯示卡')
    assert len(filter_products([p,p],base))==1
    assert filter_products([product()],base)==[]
    assert filter_products([p],base.model_copy(update={'exclude_keywords':['5070']}))==[]
    assert filter_products([p],base.model_copy(update={'max_price':100}))==[]
    assert filter_products([p],base.model_copy(update={'keyword':'RTX 5090'}))==[]


def test_dedup_new_old_and_price_history(repo):
    t=task(repo); p=product()
    first=repo.observe(t.id,p); again=repo.observe(t.id,p)
    assert first['is_new'] and not again['is_new'] and not again['price_changed']
    lower=p.model_copy(update={'price_twd':19000})
    assert repo.observe(t.id,lower)['price_dropped']
    assert len(repo.products())==1
    assert [r['price_twd'] for r in repo.history(p.product_id)]==[19000,20000]


def test_mock_run_has_no_outbound_notification(repo,monkeypatch):
    monkeypatch.setenv('DISCORD_WEBHOOK_URL','test-only-placeholder')
    async def forbidden(*args): raise AssertionError('Mock must not notify')
    result=asyncio.run(ProductMonitor(repo,notifier=forbidden).run(task(repo)))
    assert result['status']=='completed' and result['new_count']==1 and result['notified_count']==0


def test_import_notification_dedup_and_price_drop(repo,monkeypatch):
    monkeypatch.setenv('DISCORD_WEBHOOK_URL','test-only-placeholder')
    p=product(); repo.import_products([p]); t=task(repo,provider='import',notify_price_drop=True)
    sent=[]
    async def notify(p,a,url): sent.append(p['price_twd']); return True
    monitor=ProductMonitor(repo,notifier=notify)
    asyncio.run(monitor.run(t)); asyncio.run(monitor.run(t))
    repo.import_products([p.model_copy(update={'price_twd':18000})])
    asyncio.run(monitor.run(t)); asyncio.run(monitor.run(t))
    assert sent==[20000,18000]
    assert len(repo.products())==1


def test_uncertain_notification_not_retried(repo,monkeypatch):
    monkeypatch.setenv('DISCORD_WEBHOOK_URL','test-only-placeholder')
    repo.import_products([product()]); t=task(repo,provider='import'); calls=[]
    async def notify(*args): calls.append(True); return False
    monitor=ProductMonitor(repo,notifier=notify)
    first=asyncio.run(monitor.run(t)); asyncio.run(monitor.run(t))
    assert first['error_code']=='notification_failed' and len(calls)==1


@pytest.mark.parametrize('error,code',[
    (ProviderError('authorization_expired','授權已過期'),'authorization_expired'),
    (httpx.TimeoutException('secret token'),'timeout'),
    (httpx.ConnectError('secret token'),'connection_error'),
    (httpx.HTTPStatusError('secret token',request=httpx.Request('GET','https://example.test'),response=httpx.Response(429)),'rate_limited'),
    (httpx.HTTPStatusError('secret token',request=httpx.Request('GET','https://example.test'),response=httpx.Response(401)),'authorization_expired'),
])
def test_source_errors_are_safe_recorded_and_release_lock(repo,error,code):
    class Broken:
        async def search(self,task): raise error
    t=task(repo)
    result=asyncio.run(ProductMonitor(repo,providers={'mock':Broken()}).run(t))
    assert result['error_code']==code and 'secret token' not in str(result)
    assert repo.acquire(t.id)


def test_official_source_is_fail_closed(repo):
    result=asyncio.run(ProductMonitor(repo).run(task(repo,provider='shopee')))
    assert result['status']=='failed' and result['error_code']=='authorization_required'


def test_scheduler_executes_and_rejects_duplicate(repo):
    async def run():
        t=task(repo,cron='*/15 * * * *')
        rt=ShopeeRuntime(repo); rt.start()
        job=rt.scheduler.get_job(f'shopee_{t.id}')
        assert str(job.trigger.timezone)=='Asia/Taipei'
        await job.func(*job.args)
        with pytest.raises(ProviderError): await rt.start_task(t.id)
        await asyncio.gather(*list(rt.jobs.values()))
        assert repo.runs()[0]['status']=='completed'
        await rt.close()
    asyncio.run(run())


def test_ai_unavailable_keeps_product_and_no_false_recommendation(repo,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    result=asyncio.run(ProductMonitor(repo).run(task(repo,decision_mode='ai',description='保固有效')))
    assert result['error_code']=='ai_not_configured'
    assert len(repo.products())==1 and repo.products()[0]['analysis'] is None


def test_ai_failure_does_not_starve_or_drop_later_products(repo,monkeypatch):
    items=[product().model_copy(update={'product_id':f'item-{i}'}) for i in range(3)]
    repo.import_products(items)
    t=task(repo,provider='import',decision_mode='ai',description='測試需求')
    monitor=ProductMonitor(repo)
    analyzed=[]
    async def analyze(task,p):
        analyzed.append(p.product_id)
        if len(analyzed)==1: raise ProviderError('ai_invalid_response','格式無效')
        return {'recommended':False,'reason':'資訊不足','mode':'ai'}
    monkeypatch.setattr(monitor,'_analyze',analyze)
    result=asyncio.run(monitor.run(t))
    assert result['found']==3 and result['new_count']==3
    assert len(repo.products())==3 and len(analyzed)==3
    assert result['error_code']=='ai_invalid_response'


def test_custom_prompt_supplements_required_output_schema(repo):
    captured=[]
    class Client:
        def is_available(self): return True
        async def analyze(self,p,images,prompt,**kwargs):
            captured.append(prompt)
            return {'is_recommended':False,'reason':'資訊不足','risk_tags':[]}
        async def close(self): pass
    t=task(repo,decision_mode='ai',description='保固有效',custom_prompt='請注意風扇異音')
    result=asyncio.run(ProductMonitor(repo,ai_factory=Client).run(t))
    assert result['status']=='completed'
    assert 'criteria_analysis' in captured[0] and '請注意風扇異音' in captured[0]


@pytest.mark.parametrize('enabled,allowed,expected',[(False,False,[]),(True,False,[]),(False,True,[]),(True,True,['https://img.susercontent.com/test.jpg'])])
def test_ai_image_permission_applies_to_text_and_multimodal_payload(repo,enabled,allowed,expected):
    captured=[]
    class Client:
        def is_available(self): return True
        async def analyze(self,p,images,prompt,**kwargs):
            captured.append((p,kwargs['remote_image_urls']))
            return {'is_recommended':False,'reason':'資訊不足','risk_tags':[]}
        async def close(self): pass
    t=task(repo,provider='import',decision_mode='ai',description='測試',analyze_images=enabled)
    repo.import_products([product(images=['https://img.susercontent.com/test.jpg'],images_allowed=allowed)])
    asyncio.run(ProductMonitor(repo,ai_factory=Client).run(t))
    assert captured[0][0]['images']==[]
    assert captured[0][1]==expected


def test_twd_amounts_preserved_without_implicit_currency_conversion(repo):
    p=normalize_product({'product_id':'twd-test','title':'RTX 5070 Ti','price_twd':1234.5,'original_price_twd':1500})
    t=task(repo,min_price=1234,max_price=1235)
    assert filter_products([p],t)==[p]
    repo.observe(t.id,p)
    assert repo.products()[0]['price_twd']==1234.5
    assert repo.history(p.product_id)[0]['price_twd']==1234.5
    for bad in [dict(product_id='x',title='test',price=300,currency='CNY'),dict(product_id='x',title='test',price_twd=300,currency='USD')]:
        with pytest.raises(ValueError): normalize_product(bad)
