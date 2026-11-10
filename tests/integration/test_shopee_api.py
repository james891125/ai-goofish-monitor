import time
import pytest
from fastapi.testclient import TestClient
from src.app import app, SESSIONS, LOGIN_ATTEMPTS


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'app.sqlite3'))
    monkeypatch.setenv('WEB_USERNAME','test-user')
    monkeypatch.setenv('WEB_PASSWORD','test-only-password-123')
    monkeypatch.delenv('DISCORD_WEBHOOK_URL',raising=False)
    SESSIONS.clear(); LOGIN_ATTEMPTS.clear()
    with TestClient(app) as client:
        yield client


def login(client):
    response=client.post('/auth/status',json={'username':'test-user','password':'test-only-password-123'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie']


def payload(**updates):
    return dict(task_name='RTX 測試',keyword='RTX 5070 Ti',**updates)


def test_api_auth_csrf_and_logout(client):
    assert client.get('/health').status_code==200
    assert client.get('/api/shopee/settings').status_code==401
    assert client.post('/auth/status',json={'username':'test-user','password':'wrong'}).status_code==401
    login(client)
    assert client.get('/api/shopee/status').json()['release_status']=='waiting_authorization'
    assert client.post('/api/shopee/tasks',headers={'origin':'https://attacker.invalid'},json=payload()).status_code==403
    assert client.post('/auth/logout').status_code==200
    assert client.get('/api/shopee/tasks').status_code==401


def test_task_crud_manual_run_and_historical_preservation(client):
    login(client)
    created=client.post('/api/shopee/tasks',json=payload(cron='*/30 * * * *'))
    assert created.status_code==201
    task=created.json(); task_id=task['id']
    assert task['next_run_at'] is not None
    assert len(client.get('/api/shopee/tasks').json())==1
    update=payload(cron=None,min_price=15000,max_price=25000)
    assert client.put(f'/api/shopee/tasks/{task_id}',json=update).json()['min_price']==15000
    assert client.post(f'/api/shopee/tasks/{task_id}/run').status_code==202
    for _ in range(100):
        runs=client.get('/api/shopee/runs').json()
        if runs and runs[0]['status']!='running': break
        time.sleep(.01)
    assert runs[0]['status']=='completed'
    products=client.get('/api/shopee/products').json()
    assert len(products)==1 and products[0]['data_quality']=='mock'
    assert client.delete(f'/api/shopee/tasks/{task_id}').json()['history_preserved'] is True
    assert client.get('/api/shopee/tasks').json()==[]
    assert len(client.get('/api/shopee/products').json())==1
    assert client.post(f'/api/shopee/tasks/{task_id}/run').status_code==404


def test_import_rights_and_validation_are_atomic(client):
    login(client)
    good={'product_id':'1.2','title':'RTX 5070 Ti','price_twd':20000,'seller':None}
    assert client.post('/api/shopee/import',json={'products':[good]}).status_code==422
    bad=dict(good,product_id='3',price_twd=-1)
    assert client.post('/api/shopee/import',json={'products':[good,bad],'rights_confirmed':True}).status_code==422
    assert app.state.runtime.repository.imported_products()==[]
    result=client.post('/api/shopee/import',json={'products':[good],'rights_confirmed':True})
    assert result.json()=={'imported':1}
    assert app.state.runtime.repository.imported_products()[0]['seller']['rating'] is None


def test_no_active_xianyu_endpoints(client):
    login(client)
    for endpoint in ['/api/accounts','/api/tasks','/api/login-state','/api/settings/rotation']:
        assert client.get(endpoint).status_code==404


def test_bad_task_settings_and_secret_readback(client,monkeypatch):
    login(client)
    assert client.post('/api/shopee/tasks',json=payload(min_price=20,max_price=10)).status_code==422
    assert client.post('/api/shopee/tasks',json=payload(cron='bad')).status_code==422
    assert client.post('/api/shopee/tasks',json=payload(decision_mode='ai')).status_code==422
    monkeypatch.setenv('OPENAI_API_KEY','test-only-api-secret')
    monkeypatch.setenv('DISCORD_WEBHOOK_URL','test-only-discord-secret')
    text=client.get('/api/shopee/settings').text
    assert 'test-only-api-secret' not in text and 'test-only-discord-secret' not in text
    assert client.put('/api/shopee/settings',json={'OPENAI_MODEL_NAME':'ok\nWEB_PASSWORD=evil'}).status_code==422
    assert client.put('/api/shopee/settings',json={'DISCORD_WEBHOOK_URL':'https://attacker.invalid'}).status_code==422


def test_basic_auth_cannot_bypass_login_rate_limiter(client):
    import base64
    headers={'Authorization':'Basic '+base64.b64encode(b'test-user:test-only-password-123').decode()}
    assert client.get('/api/shopee/tasks',headers=headers).status_code==401
    for _ in range(10):
        assert client.post('/auth/status',json={'username':'test-user','password':'wrong'}).status_code==401
    assert client.post('/auth/status',json={'username':'test-user','password':'wrong'}).status_code==429
