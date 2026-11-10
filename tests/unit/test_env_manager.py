from src.infrastructure.config.env_manager import EnvManager


def test_get_value_prefers_env_file_when_key_present(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("WEBHOOK_URL=https://hooks.example.com/new\n", encoding="utf-8")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com/old")

    manager = EnvManager(str(env_file))

    assert manager.get_value("WEBHOOK_URL") == "https://hooks.example.com/new"


def test_get_value_falls_back_to_runtime_when_key_missing_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com/runtime")

    manager = EnvManager(str(env_file))

    assert manager.get_value("WEBHOOK_URL") == "https://hooks.example.com/runtime"


def test_invalid_unicode_does_not_truncate_existing_settings(tmp_path):
    path=tmp_path/'.env'; original='WEB_USERNAME=test\nOPENAI_API_KEY=test-only-placeholder\n'
    path.write_text(original,encoding='utf-8')
    assert not EnvManager(str(path)).update_values({'OPENAI_MODEL_NAME':'\ud800'})
    assert path.read_text(encoding='utf-8')==original
    assert list(tmp_path.iterdir())==[path]


def test_atomic_replace_failure_keeps_settings(tmp_path,monkeypatch):
    path=tmp_path/'.env'; path.write_text('WEB_USERNAME=test\n',encoding='utf-8')
    import os
    def fail(*args): raise OSError('test failure')
    monkeypatch.setattr(os,'replace',fail)
    assert not EnvManager(str(path)).update_values({'OPENAI_MODEL_NAME':'new'})
    assert path.read_text(encoding='utf-8')=='WEB_USERNAME=test\n'
    assert list(tmp_path.iterdir())==[path]


def test_persistent_settings_symlink_is_preserved(tmp_path):
    import pytest
    target=tmp_path/'settings.env'; target.write_text('WEB_USERNAME=test\n')
    link=tmp_path/'.env'
    try: link.symlink_to(target)
    except OSError: pytest.skip('OS does not permit creating test symlinks')
    assert EnvManager(str(link)).update_values({'OPENAI_MODEL_NAME':'new'})
    assert link.is_symlink() and 'OPENAI_MODEL_NAME=new' in target.read_text(encoding='utf-8')


def test_literal_dollar_syntax_round_trips_without_interpolation(tmp_path):
    path=tmp_path/'.env'
    manager=EnvManager(str(path))
    value='test-${INTENTIONALLY_MISSING_NAME}-suffix'
    assert manager.update_values({'OPENAI_API_KEY':value})
    assert manager.get_value('OPENAI_API_KEY')==value


def test_windows_utf8_bom_config_preserves_first_key(tmp_path):
    path = tmp_path / '.env'
    original = 'WEB_USERNAME=test-user\nWEB_PASSWORD=test-only-long-password\nOPENAI_API_KEY=test-${literal}-key\n'
    path.write_text(original, encoding='utf-8-sig')
    manager = EnvManager(str(path))
    assert manager.get_value('WEB_USERNAME') == 'test-user'
    assert manager.get_value('OPENAI_API_KEY') == 'test-${literal}-key'
    assert manager.update_values({'OPENAI_MODEL_NAME': 'test-model'})
    assert manager.get_value('WEB_USERNAME') == 'test-user'
    assert manager.get_value('WEB_PASSWORD') == 'test-only-long-password'
    assert not any(key.startswith('\ufeff') for key in manager.read_env())
