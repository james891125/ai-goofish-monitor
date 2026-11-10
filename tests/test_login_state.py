import json

import pytest

from shopee_lite.login_state import LoginStateError, normalize_login_state, summarize_login_state


def _cookie(name, value, **extra):
    return {"name": name, "value": value, "domain": ".shopee.tw", "path": "/", **extra}


def test_snapshot_is_normalised_and_summarised_without_secrets():
    content = json.dumps({
        "cookies": [_cookie("SPC_EC", "secret", expires=4102444800, sameSite="no_restriction"), _cookie("SPC_U", "123")],
        "env": {"navigator": {"userAgent": "UA"}},
    })

    state = normalize_login_state(content)
    summary = summarize_login_state(state)

    assert state["cookies"][0]["sameSite"] == "None" and state["env"]["navigator"]["userAgent"] == "UA"
    assert summary["logged_in"] is True and summary["shopee_user_id"] == "123" and summary["expired"] is False
    assert "secret" not in json.dumps(summary)


@pytest.mark.parametrize("content", ["hello", "{}", json.dumps({"cookies": [{"name": "a", "value": "b", "domain": ".example.com"}]})])
def test_bad_content_is_rejected(content):
    with pytest.raises(LoginStateError):
        normalize_login_state(content)


def test_plain_cookie_array_without_login_cookie_is_flagged():
    state = normalize_login_state(json.dumps([_cookie("SPC_F", "device")]))
    assert summarize_login_state(state)["logged_in"] is False
