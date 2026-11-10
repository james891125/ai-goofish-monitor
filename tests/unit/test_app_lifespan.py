"""The Shopee app must not resume or migrate legacy tasks into live jobs."""
import pytest
from fastapi.testclient import TestClient
from src.app import app


def test_lifespan_requires_secure_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'app.sqlite3'))
    monkeypatch.setenv('WEB_USERNAME','admin')
    monkeypatch.setenv('WEB_PASSWORD','admin123')
    with pytest.raises(ValueError,match='WEB_PASSWORD'):
        with TestClient(app): pass


def test_lifespan_shuts_down_scheduler(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_DATABASE_FILE',str(tmp_path/'app.sqlite3'))
    monkeypatch.setenv('WEB_USERNAME','test-user')
    monkeypatch.setenv('WEB_PASSWORD','test-only-password-123')
    with TestClient(app):
        assert app.state.runtime.scheduler.running
        assert app.state.runtime.repository.tasks()==[]
    assert app.state.runtime.jobs=={}
