import setup_env


def test_write_env_updates_in_place_and_keeps_comments(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# 帳密\nWEB_USERNAME=\nWEB_PASSWORD=\nSERVER_PORT=8000\n", encoding="utf-8")

    setup_env.write_env({"WEB_USERNAME": "me", "WEB_PASSWORD": "p@ss word#1", "NEW_KEY": "x"}, env_file)

    text = env_file.read_text(encoding="utf-8")
    assert text.startswith("# 帳密\nWEB_USERNAME=me\n")
    assert "SERVER_PORT=8000" in text and text.count("WEB_PASSWORD=") == 1
    values = setup_env.read_env(env_file)
    assert values["WEB_PASSWORD"] == "p@ss word#1"
    assert values["NEW_KEY"] == "x"


def test_written_values_are_readable_by_dotenv(tmp_path):
    from dotenv import dotenv_values

    env_file = tmp_path / ".env"
    setup_env.write_env({"WEB_PASSWORD": 'a"b c#d', "OPENAI_API_KEY": "sk-abc_123"}, env_file)

    loaded = dotenv_values(env_file, encoding="utf-8")
    assert loaded["WEB_PASSWORD"] == 'a"b c#d'
    assert loaded["OPENAI_API_KEY"] == "sk-abc_123"


def test_needs_credentials_treats_blank_and_default_password_as_unset():
    assert setup_env.needs_credentials({})
    assert setup_env.needs_credentials({"WEB_USERNAME": "admin", "WEB_PASSWORD": "admin123"})
    assert setup_env.needs_credentials({"WEB_USERNAME": "", "WEB_PASSWORD": "secret1"})
    assert not setup_env.needs_credentials({"WEB_USERNAME": "me", "WEB_PASSWORD": "secret1"})


def test_main_prompts_and_saves_when_unset(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    example = tmp_path / ".env.example"
    example.write_text("WEB_USERNAME=\nWEB_PASSWORD=\nOPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(setup_env, "ENV_FILE", env_file)
    monkeypatch.setattr(setup_env, "ENV_EXAMPLE", example)
    monkeypatch.setattr(setup_env.sys.stdin, "isatty", lambda: True, raising=False)
    answers = iter(["jimmy", "2"])
    secrets = iter(["short", "good-pass", "good-pass", "or-key"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(setup_env.getpass, "getpass", lambda prompt="": next(secrets))
    original_write = setup_env.write_env
    monkeypatch.setattr(setup_env, "write_env", lambda updates: original_write(updates, env_file))
    original_read = setup_env.read_env
    monkeypatch.setattr(setup_env, "read_env", lambda: original_read(env_file))

    assert setup_env.main() == 0

    values = original_read(env_file)
    assert values["WEB_USERNAME"] == "jimmy" and values["WEB_PASSWORD"] == "good-pass"
    assert values["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert values["OPENAI_API_KEY"] == "or-key"

    # 第二次執行不再詢問
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("不應再詢問")))
    assert setup_env.main() == 0


def test_main_fails_without_terminal_when_credentials_missing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(setup_env, "ENV_FILE", env_file)
    monkeypatch.setattr(setup_env, "ENV_EXAMPLE", tmp_path / "missing.example")
    monkeypatch.setattr(setup_env, "read_env", lambda: {})
    monkeypatch.setattr(setup_env.sys.stdin, "isatty", lambda: False, raising=False)

    assert setup_env.main() == 1
