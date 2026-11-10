"""AI 設定只依賴 OpenAI 相容欄位，不建立其他服務。"""
from src.infrastructure.config.settings import AISettings


def test_ai_settings_load_openai_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "test-model")
    monkeypatch.setenv("ENABLE_RESPONSE_FORMAT", "false")
    value = AISettings(_env_file=None)
    assert value.is_configured()
    assert value.model_name == "test-model"
    assert value.enable_response_format is False
    assert "unit-test-key" not in repr(value)


def test_ai_settings_require_complete_nonblank_connection():
    assert not AISettings(api_key=" ", base_url="https://example.com/v1", model_name="test-model", _env_file=None).is_configured()
    assert not AISettings(api_key="unit-test-key", base_url="", model_name="test-model", _env_file=None).is_configured()
    assert not AISettings(api_key="unit-test-key", base_url="https://example.com/v1", model_name="", _env_file=None).is_configured()


def test_ai_settings_do_not_create_files_or_other_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    AISettings(_env_file=None)
    assert list(tmp_path.iterdir()) == []
    assert set(AISettings.model_fields) == {
        "api_key", "base_url", "model_name", "proxy_url", "enable_response_format",
        "max_output_tokens", "product_description_chars", "max_images", "max_prompt_chars", "empty_response_retries",
    }
