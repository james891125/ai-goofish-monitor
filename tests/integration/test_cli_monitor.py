"""The source-neutral CLI now runs only source-neutral Shopee tasks."""
import asyncio
import sys
import pytest
from src.domain.models.shopee import ShopeeTask
from src.infrastructure.persistence.shopee_repository import ShopeeRepository
import monitor


def test_cli_runs_mock_without_cookie_or_prompt(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'app.sqlite3'))
    repo=ShopeeRepository()
    repo.save_task(ShopeeTask(task_name='RTX',keyword='RTX 5070 Ti'))
    monkeypatch.setattr(sys,'argv',['monitor.py','--task-name','RTX','--debug-limit','1'])
    assert asyncio.run(monitor.main())==0
    assert 'completed' in capsys.readouterr().out
    assert len(repo.products())==1


def test_cli_no_legacy_config_or_cookies(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'app.sqlite3'))
    monkeypatch.setattr(sys,'argv',['monitor.py'])
    with pytest.raises(SystemExit): asyncio.run(monitor.main())
