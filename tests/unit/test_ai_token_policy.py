"""Offline accounting, cache invalidation, permission and bounded-input regressions."""
import asyncio
import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.domain.models.shopee import Product, ShopeeTask
from src.infrastructure.config.settings import AISettings
from src.infrastructure.external.ai_client import AIClient
from src.infrastructure.persistence.shopee_repository import ShopeeRepository
from src.services.ai_token_policy import analysis_cache_key, project_product
from src.services.product_monitor import ProductMonitor
from tests.unit.test_shopee_ai_analysis import ANALYSIS


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.delenv('DISCORD_WEBHOOK_URL', raising=False)
    repo = ShopeeRepository(str(tmp_path / 'app.sqlite3'))
    task = repo.save_task(ShopeeTask(task_name='顯示卡', keyword='RTX', provider='import',
                                   decision_mode='ai', description='需要保固與公開賣家資料'))
    product = Product(product_id='item-1', title='RTX 5070 Ti', price_twd=20000, data_source='import')
    settings = AISettings(_env_file=None, api_key='test-secret-never-save', base_url='https://ai.example/v1', model_name='test-model')
    state = SimpleNamespace(calls=[], settings=settings, result=copy.deepcopy(ANALYSIS), products=[product], closed=0)

    class Provider:
        async def search(self, task):
            return list(state.products)

    class Client:
        def __init__(self): self.settings = state.settings
        def is_available(self): return True
        async def analyze(self, product, paths, prompt, **kwargs):
            # Every filtered product must be persisted before the first remote request.
            assert len(repo.products(task.id)) == len({p.product_id for p in state.products if 'RTX' in p.title})
            state.calls.append((copy.deepcopy(product), prompt, kwargs))
            return copy.deepcopy(state.result)
        async def close(self): state.closed += 1

    monitor = ProductMonitor(repo, providers={'import': Provider()}, ai_factory=Client)
    return repo, task, product, state, monitor


def run(monitor, task):
    return asyncio.run(monitor.run(task))


def test_unchanged_analysis_reused_after_restart_and_fresh_collection_timestamp(context):
    repo, task, product, state, monitor = context
    first = run(monitor, task)
    state.products = [product.model_copy(update={'collected_at': '2030-01-01T00:00:00Z'})]
    reopened = ShopeeRepository(repo.db_path)
    monitor = ProductMonitor(reopened, providers=monitor.providers, ai_factory=monitor.ai_factory)
    second = run(monitor, task)
    assert first['ai_new_count'] == 1 and first['ai_reused_count'] == 0
    assert second['ai_new_count'] == 0 and second['ai_reused_count'] == 1
    assert len(state.calls) == 1 and state.closed == 2
    assert reopened.products()[0]['analysis']['recommended'] is False
    assert len(reopened.history(product.product_id)) == 1


@pytest.mark.parametrize('change', [
    {'price_twd': 19000}, {'original_price_twd': 22000}, {'title': 'RTX 5080'},
    {'description': '仍有保固'}, {'condition': 'used'}, {'category': '顯示卡'},
    {'images_allowed': True}, {'images': ['https://img.susercontent.com/new.jpg']},
    {'seller': {'rating': 4.9}}, {'data_quality': 'complete'},
])
def test_meaningful_product_changes_invalidate_cache(context, change):
    _, task, product, state, monitor = context
    run(monitor, task)
    state.products = [Product.model_validate({**product.model_dump(), **change})]
    result = run(monitor, task)
    assert len(state.calls) == 2 and result['ai_new_count'] == 1 and result['ai_reused_count'] == 0


@pytest.mark.parametrize('change', [
    {'description': '希望安靜運轉'}, {'custom_prompt': '注意風扇異音'}, {'keyword': 'RTX 5070'},
    {'min_price': 100}, {'max_price': 25000}, {'exclude_keywords': ['空盒']},
    {'analyze_images': True},
])
def test_criteria_and_image_opt_in_changes_invalidate_cache(context, change):
    _, task, _, state, monitor = context
    run(monitor, task)
    result = run(monitor, task.model_copy(update=change))
    assert result['ai_new_count'] == 1 and len(state.calls) == 2


@pytest.mark.parametrize('change', [
    {'model_name': 'another-model'}, {'base_url': 'https://other.example/v1'},
    {'base_url': 'https://ai.example/v2'}, {'base_url': 'https://ai.example/v1?api-version=next'},
    {'enable_response_format': False}, {'max_output_tokens': 1600},
    {'product_description_chars': 1000}, {'max_images': 1}, {'max_prompt_chars': 11000},
])
def test_inference_setting_changes_invalidate_cache(context, change):
    _, task, _, state, monitor = context
    run(monitor, task)
    state.settings = state.settings.model_copy(update=change)
    assert run(monitor, task)['ai_new_count'] == 1
    assert len(state.calls) == 2


@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_base_system_prompt_change_invalidates_cache(context, monkeypatch, tmp_path, newline):
    _, task, _, state, monitor = context
    original = Path('prompts/base_prompt.txt').read_text(encoding='utf-8')
    prompt_file = tmp_path / 'prompts' / 'base_prompt.txt'
    prompt_file.parent.mkdir()
    prompt_file.write_text(original, encoding='utf-8', newline=newline)
    monkeypatch.chdir(tmp_path)
    assert run(monitor, task)['ai_new_count'] == 1

    # Edit a real UTF-8 file. String comparisons of native path separators do
    # not work across Windows and POSIX, and must not decide whether it changes.
    addition = '請確認配件完整度。'
    prompt_file.write_text(original + '\n' + addition, encoding='utf-8', newline=newline)
    result = run(monitor, task)
    assert result['ai_new_count'] == 1 and result['ai_reused_count'] == 0
    assert len(state.calls) == 2
    assert addition not in state.calls[0][1] and addition in state.calls[1][1]


def test_non_decision_task_changes_and_api_key_rotation_reuse_cache(context):
    _, task, _, state, monitor = context
    run(monitor, task)
    state.settings = state.settings.model_copy(update={'api_key': 'another-test-secret'})
    task = task.model_copy(update={'task_name': '新名稱', 'cron': '0 * * * *', 'notify': 'all', 'max_items': 100})
    assert run(monitor, task)['ai_reused_count'] == 1 and len(state.calls) == 1


def test_failure_or_malformed_response_never_cached_and_stale_result_cleared(context):
    repo, task, _, state, monitor = context
    run(monitor, task)
    changed = task.model_copy(update={'description': '新條件'})
    for invalid in (None, {'is_recommended': True}, {**ANALYSIS, 'is_recommended': 'true'}):
        state.result = invalid
        result = run(monitor, changed)
        assert result['error_code'] == 'ai_invalid_response'
        assert result['ai_new_count'] == 1 and result['ai_reused_count'] == 0
        assert repo.products()[0]['analysis'] is None
    assert len(state.calls) == 4
    state.result = copy.deepcopy(ANALYSIS)
    assert run(monitor, changed)['ai_new_count'] == 1
    assert run(monitor, changed)['ai_reused_count'] == 1


def test_corrupt_cached_output_is_revalidated(context):
    repo, task, _, state, monitor = context
    run(monitor, task)
    with repo.connection() as conn:
        conn.execute('UPDATE shopee_analysis_cache SET analysis=?', ('{"recommended":true}',))
        conn.commit()
    assert run(monitor, task)['ai_new_count'] == 1 and len(state.calls) == 2


def test_cache_ui_recommendation_is_derived_from_validated_boolean(context):
    repo, task, _, state, monitor = context
    run(monitor, task)
    with repo.connection() as conn:
        bad = {**ANALYSIS, 'recommended': True}
        conn.execute('UPDATE shopee_analysis_cache SET analysis=?', (json.dumps(bad),))
        conn.commit()
    assert run(monitor, task)['ai_reused_count'] == 1
    assert repo.products()[0]['analysis']['recommended'] is False


def test_keyword_mode_never_constructs_client(context):
    _, task, _, state, monitor = context
    def forbidden(): raise AssertionError('Keyword mode must be 0 AI')
    monitor.ai_factory = forbidden
    result = run(monitor, task.model_copy(update={'decision_mode': 'keyword'}))
    assert result['status'] == 'completed' and result['ai_skipped_count'] == 1
    assert result['ai_new_count'] == result['ai_reused_count'] == 0 and state.calls == []


def test_keyword_price_and_exclusion_filters_run_before_ai(context):
    _, task, product, state, monitor = context
    state.products = [
        product.model_copy(update={'product_id': 'wrong-keyword', 'title': 'not relevant'}),
        product.model_copy(update={'product_id': 'too-expensive', 'price_twd': 30000}),
        product.model_copy(update={'product_id': 'excluded', 'title': 'RTX 空盒'}),
    ]
    def forbidden(): raise AssertionError('No filtered product may reach AI')
    monitor.ai_factory = forbidden
    result = run(monitor, task.model_copy(update={'max_price': 25000, 'exclude_keywords': ['空盒']}))
    assert result['found'] == 0 and result['ai_skipped_count'] == 3 and state.calls == []


def test_bounded_allowlist_projection_and_hidden_tail_change(context):
    _, task, product, state, monitor = context
    long_product = product.model_copy(update={'description': '明' * 20000,
        'seller': product.seller.model_copy(update={'name': '隱' * 100000, 'location': '臺' * 100000}),
        'product_url': 'https://shopee.tw/item?tracking=sensitive',
        'images': ['https://img.susercontent.com/private.jpg']})
    state.products = [long_product]
    assert run(monitor, task)['ai_new_count'] == 1
    sent = state.calls[0][0]
    assert len(sent['description']) == 2000 and sent['description_truncated'] is True
    assert len(sent['seller']['location']) == 160
    assert 'name' not in sent['seller'] and 'product_url' not in sent and 'collected_at' not in sent
    assert sent['images'] == [] and len(json.dumps(sent, ensure_ascii=False)) < 4000
    state.products = [long_product.model_copy(update={'description': '明' * 19999 + '暗'})]
    assert run(monitor, task)['ai_new_count'] == 1
    assert state.calls[0][0] == state.calls[1][0]  # Even omitted meaningful changes invalidate.


def test_images_require_both_permissions_and_are_capped(context):
    _, task, product, state, monitor = context
    urls = [f'https://img.susercontent.com/{i}.jpg' for i in range(6)]
    state.products = [product.model_copy(update={'images': urls, 'images_allowed': True})]
    run(monitor, task)
    assert state.calls[-1][2]['remote_image_urls'] == []
    run(monitor, task.model_copy(update={'analyze_images': True}))
    assert state.calls[-1][2]['remote_image_urls'] == urls[:2]
    assert state.calls[-1][0]['images'] == []
    state.products = [state.products[0].model_copy(update={'images_allowed': False})]
    run(monitor, task.model_copy(update={'analyze_images': True}))
    assert state.calls[-1][2]['remote_image_urls'] == []


def test_oversized_prompt_rejected_without_ai_not_silently_truncated(context):
    repo, task, _, state, monitor = context
    task = task.model_copy(update={'custom_prompt': '需' * 12000})
    result = run(monitor, task)
    assert result['error_code'] == 'ai_prompt_too_large' and result['ai_skipped_count'] == 1
    assert state.calls == [] and repo.products()[0]['analysis'] is None


def test_cache_key_contains_no_secrets_and_current_entry_replaced(context):
    repo, task, product, state, monitor = context
    settings = state.settings.model_copy(update={'base_url': 'https://user:password@ai.example/v1?api_key=hidden&api-version=1'})
    key = analysis_cache_key(task, product, 'prompt', settings, [])
    safe = state.settings.model_copy(update={'base_url': 'https://ai.example/v1?api-version=1', 'api_key': 'different'})
    assert key == analysis_cache_key(task, product, 'prompt', safe, [])
    assert len(key) == 64
    run(monitor, task)
    run(monitor, task.model_copy(update={'description': '新的需求'}))
    with repo.connection() as conn:
        rows = [dict(row) for row in conn.execute('SELECT * FROM shopee_analysis_cache')]
    assert len(rows) == 1 and 'test-secret-never-save' not in json.dumps(rows)


def test_cached_notification_dedup_and_price_drop_unchanged(context, monkeypatch):
    _, task, product, state, monitor = context
    monkeypatch.setenv('DISCORD_WEBHOOK_URL', 'test-placeholder-not-a-real-webhook')
    task = task.model_copy(update={'notify_price_drop': True})
    state.result['is_recommended'] = True
    sent = []
    async def notify(product, analysis, webhook):
        sent.append(product['price_twd'])
        return True
    monitor.notifier = notify
    run(monitor, task)
    assert run(monitor, task)['ai_reused_count'] == 1
    state.products = [product.model_copy(update={'price_twd': 19000})]
    run(monitor, task)
    run(monitor, task)
    assert sent == [20000, 19000] and len(state.calls) == 2


def test_batch_persisted_even_when_first_ai_raises(context):
    repo, task, product, state, monitor = context
    state.products = [product.model_copy(update={'product_id': str(i)}) for i in range(3)]
    state.result = None
    result = run(monitor, task)
    assert result['found'] == 3 and result['ai_new_count'] == 3
    assert len(state.calls) == len(repo.products()) == 3
    assert all(p['analysis'] is None for p in repo.products())


@pytest.mark.parametrize('model,field', [('test-model', 'max_tokens'), ('gpt-5-mini', 'max_completion_tokens')])
def test_client_uses_conservative_configurable_output_limit(model, field):
    client = AIClient.__new__(AIClient)
    client.settings = SimpleNamespace(model_name=model, enable_response_format=False, max_output_tokens=900)
    history = []
    async def create(**kwargs):
        history.append(kwargs)
        return SimpleNamespace(output_text='{}')
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    asyncio.run(client._call_ai([{'role': 'user', 'content': 'JSON'}]))
    assert history[0][field] == 900


def test_empty_retry_configuration_stays_bounded():
    client = AIClient.__new__(AIClient)
    client.settings = SimpleNamespace(model_name='test-model', enable_response_format=False, empty_response_retries=1)
    history = []
    async def create(**kwargs):
        history.append(kwargs)
        return SimpleNamespace(output_text='')
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(ValueError):
        asyncio.run(client._call_ai([{'role': 'user', 'content': 'JSON'}]))
    assert len(history) == 2 and history[0]['max_tokens'] == 1200


@pytest.mark.parametrize('field,value', [
    ('max_output_tokens', 0), ('max_output_tokens', 4001), ('product_description_chars', 20000),
    ('max_images', 5), ('empty_response_retries', 2), ('max_prompt_chars', 40001),
])
def test_budget_settings_reject_unbounded_values(field, value):
    with pytest.raises(ValidationError):
        AISettings(_env_file=None, **{field: value})


def test_additive_metrics_migration_preserves_old_runs_and_user_tables(tmp_path):
    path = str(tmp_path / 'old.sqlite3')
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE shopee_runs (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                found INTEGER NOT NULL DEFAULT 0, new_count INTEGER NOT NULL DEFAULT 0,
                changed_count INTEGER NOT NULL DEFAULT 0, notified_count INTEGER NOT NULL DEFAULT 0,
                error_code TEXT, error_message TEXT);
            INSERT INTO shopee_runs(id,task_id,started_at,status,found) VALUES(1,7,'old','completed',3);
            CREATE TABLE user_history(value TEXT);
            INSERT INTO user_history VALUES('keep');
        ''')
    repo = ShopeeRepository(path)
    ShopeeRepository(path)
    row = repo.runs()[0]
    assert row['found'] == 3 and row['ai_new_count'] == row['ai_reused_count'] == row['ai_skipped_count'] == 0
    with repo.connection() as conn:
        assert conn.execute('SELECT value FROM user_history').fetchone()[0] == 'keep'
