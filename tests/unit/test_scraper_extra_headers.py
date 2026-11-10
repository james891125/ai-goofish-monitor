from src.scraper import _build_extra_headers


def test_build_extra_headers_drops_fetch_metadata_that_blanks_document():
    headers = _build_extra_headers(
        {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": "secret=1",
            "Referer": "https://shopee.tw/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0",
            "sec-ch-ua": '"Chromium"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Content-Length": "0",
        }
    )

    assert headers == {
        "Accept-Language": "zh-CN,zh;q=0.9",
        "sec-ch-ua": '"Chromium"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }


def test_persist_session_cookies_updates_only_cookies(tmp_path):
    import json

    from src.scraper import persist_session_cookies

    state = tmp_path / "shopee.json"
    snapshot = {"cookies": [{"name": "old", "domain": ".shopee.tw"}], "env": {"navigator": {"userAgent": "UA"}}}
    fresh = [
        {"name": "SPC_EC", "value": "new", "domain": ".shopee.tw", "path": "/"},
        {"name": "other", "value": "x", "domain": ".example.com", "path": "/"},
    ]

    assert persist_session_cookies(str(state), snapshot, fresh) is True

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert [c["name"] for c in saved["cookies"]] == ["SPC_EC"]
    assert saved["env"]["navigator"]["userAgent"] == "UA"
    assert persist_session_cookies(str(state), snapshot, [fresh[1]]) is False
