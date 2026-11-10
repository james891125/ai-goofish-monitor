"""Offline integration of manually imported experimental snapshots, never a website."""
import time

import pytest
from fastapi.testclient import TestClient
from src.app import app, LOGIN_ATTEMPTS, SESSIONS
from tests.unit.test_shopee_ai_analysis import ANALYSIS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATABASE_FILE', str(tmp_path / 'snapshots.sqlite3'))
    monkeypatch.setenv('WEB_USERNAME', 'snapshot-test')
    monkeypatch.setenv('WEB_PASSWORD', 'test-only-snapshot-secret')
    monkeypatch.delenv('DISCORD_WEBHOOK_URL', raising=False)
    SESSIONS.clear()
    LOGIN_ATTEMPTS.clear()
    with TestClient(app) as client:
        yield client


def login(client):
    assert client.post('/auth/status', json={
        'username': 'snapshot-test', 'password': 'test-only-snapshot-secret'
    }).status_code == 200


def row(price=20000):
    return dict(product_id='123.456', title='RTX 5070 Ti', price_twd=price,
                product_url='https://shopee.tw/product/123/456', collected_at='2026-01-01T00:00:00+00:00')


def request(products=None, **overrides):
    return dict(products=products or [row()], rights_confirmed=True, risk_confirmed=True, **overrides)


def task(**overrides):
    values = dict(task_name='實驗快照', keyword='RTX', provider='browser_experiment',
                  max_items=5, max_pages=1, cron=None, decision_mode='ai', description='分析型號與交易風險')
    return {**values, **overrides}


def wait_run(client):
    for _ in range(100):
        runs = client.get('/api/shopee/runs').json()
        if runs and runs[0]['status'] != 'running':
            return runs[0]
        time.sleep(.01)
    pytest.fail('Offline snapshot job did not finish')


def test_import_requires_login_both_confirmations_and_same_origin(client):
    assert client.post('/api/shopee/browser-import', json=request()).status_code == 401
    login(client)
    for missing in ['rights_confirmed', 'risk_confirmed']:
        payload = request()
        payload[missing] = False
        assert client.post('/api/shopee/browser-import', json=payload).status_code == 422
    assert client.post('/api/shopee/browser-import', json=request(),
                       headers={'origin': 'https://external.invalid'}).status_code == 403
    assert app.state.runtime.repository.browser_snapshots() == []


def test_import_limits_and_validation_are_atomic_and_separate(client):
    login(client)
    assert client.post('/api/shopee/browser-import', json=request([row()] * 6)).status_code == 422
    for bad in [dict(row(), currency='USD'), dict(row(), price_twd=-1),
                dict(row(), collected_at=None), dict(row(), collected_at='2026-01-01T00:00:00'),
                dict(row(), collected_at='9999-01-01T00:00:00+00:00'),
                dict(row(), images_allowed=True),
                dict(row(), images=['https://down-tw.img.susercontent.com/test']),
                dict(row(), product_url='https://external.invalid/123')]:
        assert client.post('/api/shopee/browser-import', json=request([row(), bad])).status_code == 422
        assert app.state.runtime.repository.browser_snapshots() == []
    assert client.post('/api/shopee/browser-import', json=request()).json() == {'imported': 1}
    snapshot = app.state.runtime.repository.browser_snapshots()[0]
    assert snapshot['data_source'] == 'browser_experiment'
    assert snapshot['data_quality'] == 'partial'
    assert snapshot['collected_at'] == '2026-01-01T00:00:00+00:00'
    assert snapshot['seller']['rating'] is None and snapshot['images'] == []
    assert app.state.runtime.repository.imported_products() == []


def test_snapshot_provider_is_manual_only_not_official_access(client):
    login(client)
    providers = {p['id']: p for p in client.get('/api/shopee/status').json()['providers']}
    snapshot = providers['browser_experiment']
    assert snapshot['authorization_status'] == 'experimental_unverified'
    assert snapshot['live_search'] is False and snapshot['manual_only'] is True
    assert snapshot['capabilities']['condition'] is False
    assert providers['shopee']['available'] is False
    for settings in [dict(cron='0 * * * *'), dict(max_items=6), dict(max_pages=2), dict(decision_mode='keyword')]:
        assert client.post('/api/shopee/tasks', json=task(**settings)).status_code == 422
    created = client.post('/api/shopee/tasks', json=task()).json()
    assert created['next_run_at'] is None


def test_manual_snapshot_analysis_dedup_and_new_price_history(client):
    class MockAI:
        calls = 0
        def is_available(self): return True
        async def analyze(self, *args, **kwargs):
            MockAI.calls += 1
            return ANALYSIS.copy()
        async def close(self): pass

    login(client)
    app.state.runtime.monitor.ai_factory = MockAI
    assert client.post('/api/shopee/browser-import', json=request()).status_code == 200
    task_id = client.post('/api/shopee/tasks', json=task()).json()['id']
    for expected_new in [1, 0]:
        assert client.post(f'/api/shopee/tasks/{task_id}/run').status_code == 202
        run = wait_run(client)
        assert run['status'] == 'completed'
        assert run['new_count'] == expected_new
    products = client.get('/api/shopee/products').json()
    assert len(products) == 1 and products[0]['price_twd'] == 20000
    assert products[0]['data_source'] == 'browser_experiment'
    assert products[0]['collected_at'] == '2026-01-01T00:00:00+00:00'
    assert products[0]['analysis']['mode'] == 'ai'
    assert MockAI.calls == 1
    assert client.post('/api/shopee/browser-import', json=request([row(19000)])).status_code == 200
    assert client.post(f'/api/shopee/tasks/{task_id}/run').status_code == 202
    assert wait_run(client)['changed_count'] == 1
    assert MockAI.calls == 2
    prices = client.get('/api/shopee/products/123.456/history').json()
    assert [point['price_twd'] for point in prices] == [19000, 20000]
    assert client.delete(f'/api/shopee/tasks/{task_id}').status_code == 200
    assert len(client.get('/api/shopee/products/123.456/history').json()) == 2


def test_experiment_missing_ai_does_not_fall_back_to_keyword(client, monkeypatch):
    for key in ['OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL_NAME']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    login(client)
    assert client.post('/api/shopee/browser-import', json=request()).status_code == 200
    task_id = client.post('/api/shopee/tasks', json=task()).json()['id']
    assert client.post(f'/api/shopee/tasks/{task_id}/run').status_code == 202
    run = wait_run(client)
    assert run['status'] == 'failed' and run['error_code'] == 'ai_not_configured'
    assert run['ai_new_count'] == 0
    assert client.get('/api/shopee/products').json()[0]['analysis'] is None
