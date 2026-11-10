"""Offline synthetic DOM and fake-browser tests. Never connects to Shopee."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.domain.models.shopee import Product
from src.experimental.browser_collector import (
    CHANNELS, HOME_URL, SOURCE, CollectionRequest, CollectionResult,
    CollectionStopped, NavigationGuard, StopCode, VISIBLE_SNAPSHOT_JS,
    canonical_product_url, collect, product_from_snapshot, run_cli, write_result,
)

P1 = "https://shopee.tw/product/123/456"
P2 = "https://shopee.tw/product/123/789"
P3 = "https://shopee.tw/product/123/999"


def snapshot(**overrides):
    return dict(titles=["測試商品"], prices=["NT$ 1,234"], links=[],
                verification=False, login=False, blocked=False, limit=False, **{}) | overrides


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


class FakePage:
    def __init__(self, pages=None):
        self.pages = {HOME_URL: snapshot(titles=[], prices=[])} | (pages or {})
        self.main_frame = SimpleNamespace(parent_frame=None)
        self.url = "about:blank"
        self.calls = []
        self.network_urls = []
        self.waits = []
        self.evaluations = []
        self.closed = False
        self.route_handler = None
        self.response_handler = None
        self.wait_callback = None
        self.context = SimpleNamespace(route=self.set_route)

    def set_route(self, pattern, handler):
        assert pattern == "**/*"
        self.route_handler = handler

    def on(self, event, handler):
        assert event == "response"
        self.response_handler = handler

    def request(self, url, resource_type="document", frame=None):
        return SimpleNamespace(url=url, frame=frame or self.main_frame, resource_type=resource_type,
                               is_navigation_request=lambda: resource_type == "document", redirected_from=None)

    def goto(self, url, **kwargs):
        assert kwargs == {"wait_until": "load"}
        self.calls.append(url)
        request = self.request(url)
        route = FakeRoute(request)
        self.route_handler(route)
        if route.aborted:
            raise RuntimeError("raw browser message must not be output")
        info = self.pages[url]
        if isinstance(info, BaseException):
            raise info
        chain = [url] + info.get("redirect_chain", ([info["redirect"]] if info.get("redirect") else []))
        previous = None
        for index, current in enumerate(chain):
            # Match real Playwright semantics: only the first URL is routed.
            # Later redirect hops may begin before the response latch fires.
            self.network_urls.append(current)
            self.url = current
            request = self.request(current)
            request.redirected_from = previous
            destination = chain[index + 1] if index + 1 < len(chain) else None
            response = SimpleNamespace(status=302 if destination else info.get("status", 200),
                                       url=current, request=request,
                                       header_value=lambda _, target=destination: target)
            self.response_handler(response)
            previous = request
        return response

    def evaluate(self, script, args):
        assert script == VISIBLE_SNAPSHOT_JS
        assert 1 <= args["maxLinks"] <= 5
        self.evaluations.append(self.url)
        return self.pages[self.url]

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        if self.wait_callback:
            self.wait_callback(self)


class FakeSession:
    def __init__(self, page):
        self.page = page
        self.channels = []
        self.entered = False

    @contextmanager
    def __call__(self, channel):
        self.channels.append(channel)
        self.entered = True
        try:
            yield self.page
        finally:
            self.page.closed = True


def run_fake(request=None, pages=None, **kwargs):
    page = FakePage(pages or {P1: snapshot()})
    session = FakeSession(page)
    result = collect(request or CollectionRequest(urls=(P1,)), channel="chromium",
                     confirm_manual=kwargs.pop("confirm_manual", lambda: True),
                     session_factory=session, **kwargs)
    return result, page, session


@pytest.mark.parametrize("url", [
    P1, P1 + "?tracking=discard#discard", "https://www.shopee.tw/商品-i.123.456?x=1",
    "https://shopee.tw/%E5%95%86%E5%93%81-i.123.456", "https://shopee.tw/product/123/456/",
])
def test_canonical_product_urls_strip_tracking(url):
    assert canonical_product_url(url) == P1


@pytest.mark.parametrize("url", [
    "http://shopee.tw/product/123/456", "https://shopee.tw:443/product/123/456",
    "https://shopee.tw:80/product/123/456", "https://user:pass@shopee.tw/product/123/456",
    "https://shopee.tw.evil.test/product/123/456", "https://shopee.tw./product/123/456",
    "https://seller.shopee.tw/product/123/456", "https://evil.test/product/123/456",
    "https://shopee.tw/search?keyword=a", "https://shopee.tw/buyer/login", "https://shopee.tw/",
    "https://shopee.tw/product/x/456", "https://shopee.tw/product/0/456", "https://shopee.tw/product/123/456/extra",
    "https://shopee.tw/../product/123/456", "https://shopee.tw/xx%2Fxx-i.123.456",
    "https://shopee.tw/xx%00-i.123.456", "https://shopee.tw\\@evil.test/product/123/456",
    " https://shopee.tw/product/123/456", "https://shopee.tw/\nproduct/123/456", "/product/123/456",
    "javascript:alert(1)", "data:text/html,a", None, 1,
])
def test_reject_unsafe_or_nonproduct_urls(url):
    with pytest.raises(ValueError):
        canonical_product_url(url)


@pytest.mark.parametrize("payload", [
    {}, {"keyword": ""}, {"keyword": None}, {"urls": []}, {"urls": "bad"},
    {"keyword": "a", "urls": [P1]}, {"keyword": 1}, {"keyword": "x\n"},
    {"keyword": "x", "max_items": 0}, {"keyword": "x", "max_items": 6},
    {"keyword": "x", "max_items": True}, {"keyword": "x", "max_items": 1.5},
    {"keyword": "x", "interval_seconds": 59}, {"keyword": "x", "interval_seconds": 301},
    {"keyword": "x", "interval_seconds": True}, {"keyword": "x", "interval_seconds": 60.5},
    {"urls": [P1] * 6}, {"keyword": "x", "cookies": "not allowed"},
    {"keyword": "x", "headless": True}, {"keyword": "x", "pages": 2},
])
def test_request_limits_are_not_overridable(payload):
    with pytest.raises(ValueError):
        CollectionRequest.from_dict(payload)


def test_request_download_shape_and_modes():
    request = CollectionRequest.from_dict({"keyword": " 相機 ", "urls": [], "max_items": 1, "interval_seconds": 300})
    assert request.keyword == "相機"
    assert request.search_url == "https://shopee.tw/search?keyword=%E7%9B%B8%E6%A9%9F"
    request = CollectionRequest.from_dict({"keyword": None, "urls": [P1, P1 + "?duplicate=yes"]})
    assert request.urls == (P1,)
    assert CollectionRequest.from_dict({"keyword": "", "urls": [P1]}).urls == (P1,)


def test_product_shape_preserves_only_supported_evidence():
    product = product_from_snapshot(snapshot(), P1)
    Product.model_validate(product)
    assert product["product_id"] == "123.456"
    assert product["price_twd"] == 1234
    assert product["data_source"] == SOURCE
    assert product["data_quality"] == "partial"
    assert product["images_allowed"] is False and product["images"] == []
    assert product["condition"] is None and product["category"] is None
    assert all(value is None for value in product["seller"].values())
    assert product["description"] == ""


@pytest.mark.parametrize("price", ["NT$ 0", "NT$ 1234", "TWD 1,234.50", "價格：NT$ 200", "Price: TWD 2.50"])
def test_explicit_currency_price(price):
    assert product_from_snapshot(snapshot(prices=[price]), P1)["price_twd"] >= 0


@pytest.mark.parametrize("prices,code", [
    ([], StopCode.MISSING_PRICE), (["$ 123"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ 1", "TWD 2"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ 100 - NT$ 200"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ 10～20"], StopCode.AMBIGUOUS_PRICE), (["NT$ 1,23"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ -1"], StopCode.AMBIGUOUS_PRICE), (["NT$ 1.222"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ 1,000,000,001"], StopCode.AMBIGUOUS_PRICE),
    (["NT$ NaN"], StopCode.AMBIGUOUS_PRICE), (["NT$ 100 運費 NT$ 60"], StopCode.AMBIGUOUS_PRICE),
])
def test_ambiguous_or_missing_prices_stop(prices, code):
    with pytest.raises(CollectionStopped) as error:
        product_from_snapshot(snapshot(prices=prices), P1)
    assert error.value.code == code


def test_duplicate_equal_prices_are_unambiguous():
    assert product_from_snapshot(snapshot(prices=["NT$ 1,234", "TWD 1234.00"]), P1)["price_twd"] == 1234


@pytest.mark.parametrize("fields,code", [
    ({"titles": []}, StopCode.MISSING_TITLE), ({"titles": ["A", "B"]}, StopCode.AMBIGUOUS_TITLE),
    ({"verification": True}, StopCode.VERIFICATION_REQUIRED), ({"login": True}, StopCode.AUTH_REQUIRED),
    ({"blocked": True}, StopCode.ACCESS_BLOCKED), ({"limit": True}, StopCode.DOM_LIMIT),
])
def test_fail_closed_dom_signals(fields, code):
    with pytest.raises(CollectionStopped) as error:
        product_from_snapshot(snapshot(**fields), P1)
    assert error.value.code == code


def test_url_batch_sequential_fixed_delay_and_cleanup():
    result, page, session = run_fake(CollectionRequest(urls=(P1, P2), interval_seconds=61),
                                    {P1: snapshot(), P2: snapshot(prices=["TWD 200"])})
    assert result.code == StopCode.COMPLETED
    assert len(result.products) == 2
    assert page.calls == [HOME_URL, P1, P2]
    assert page.waits == [1000] * 122
    assert page.closed and session.channels == ["chromium"]


def test_keyword_discovers_only_one_visible_search_page_then_products():
    request = CollectionRequest(keyword="相機", max_items=2)
    result, page, _ = run_fake(request, {
        request.search_url: snapshot(links=[P1 + "?ad=tracking", P2, P3]),
        P1: snapshot(), P2: snapshot(), P3: snapshot(),
    })
    assert result.code == StopCode.COMPLETED
    assert page.calls == [HOME_URL, request.search_url, P1, P2]
    assert page.waits == [1000] * 180
    assert len(result.products) == 2
    assert page.closed


def test_no_visible_search_links_stops_without_pagination():
    request = CollectionRequest(keyword="missing")
    result, page, _ = run_fake(request, {request.search_url: snapshot(links=[])})
    assert result.code == StopCode.EMPTY_RESULTS
    assert page.calls == [HOME_URL, request.search_url]


@pytest.mark.parametrize("fields,code", [
    ({"status": 401}, StopCode.HTTP_BLOCKED), ({"status": 403}, StopCode.HTTP_BLOCKED),
    ({"status": 429}, StopCode.HTTP_BLOCKED), ({"login": True}, StopCode.AUTH_REQUIRED),
    ({"verification": True}, StopCode.VERIFICATION_REQUIRED), ({"blocked": True}, StopCode.ACCESS_BLOCKED),
    ({"titles": []}, StopCode.MISSING_TITLE), ({"prices": []}, StopCode.MISSING_PRICE),
    ({"prices": ["NT$ 1", "NT$ 2"]}, StopCode.AMBIGUOUS_PRICE),
])
def test_stop_before_next_url_and_preserve_completed_products(fields, code):
    result, page, _ = run_fake(CollectionRequest(urls=(P1, P2, P3)),
                               {P1: snapshot(), P2: snapshot(**fields), P3: snapshot()})
    assert result.code == code and result.exit_code != 0
    assert len(result.products) == 1
    assert page.calls == [HOME_URL, P1, P2]
    assert page.closed


@pytest.mark.parametrize("redirect", ["https://evil.test/product/123/456", "https://shopee.tw/buyer/login", P3,
                                      "https://shopee.tw/search?keyword=unexpected"])
def test_redirect_latched_before_extraction_without_retry(redirect):
    result, page, _ = run_fake(CollectionRequest(urls=(P1, P2)), {P1: snapshot(redirect=redirect), P2: snapshot()})
    assert result.code == (StopCode.AUTH_REQUIRED if "buyer/login" in redirect else StopCode.UNEXPECTED_ROUTE)
    assert page.calls == [HOME_URL, P1]
    assert page.closed and not result.products


def test_user_cancellation_before_launch():
    result, page, session = run_fake(cancelled=lambda: True)
    assert result.code == StopCode.CANCELLED and result.exit_code == 130
    assert not session.entered and not page.calls


def test_user_cancellation_at_manual_prompt_cleans_up():
    result, page, _ = run_fake(confirm_manual=lambda: False)
    assert result.code == StopCode.CANCELLED and page.closed
    assert page.calls == [HOME_URL]


def test_ctrl_c_preserves_products_and_cleans_up():
    result, page, _ = run_fake(CollectionRequest(urls=(P1, P2)), {P1: snapshot(), P2: KeyboardInterrupt()})
    assert result.code == StopCode.CANCELLED and page.closed
    assert len(result.products) == 1


def test_block_during_delay_stops_before_another_navigation():
    page = FakePage({P1: snapshot(), P2: snapshot()})
    def block_after_first_product(p):
        if p.url == P1:
            p.response_handler(SimpleNamespace(status=429, request=p.request(P1)))
    page.wait_callback = block_after_first_product
    result = collect(CollectionRequest(urls=(P1, P2)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.HTTP_BLOCKED
    assert len(result.products) == 1
    assert page.calls == [HOME_URL, P1] and page.closed
    assert len(page.waits) == 61


def test_challenge_appearing_during_delay_stops_immediately():
    page = FakePage({P1: snapshot()})
    def challenge(p):
        p.pages[HOME_URL] = snapshot(verification=True)
    page.wait_callback = challenge
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.VERIFICATION_REQUIRED
    assert page.calls == [HOME_URL] and len(page.waits) == 1 and page.closed


def test_cancellation_during_delay():
    page = FakePage({P1: snapshot()})
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page), cancelled=lambda: bool(page.waits))
    assert result.code == StopCode.CANCELLED
    assert page.calls == [HOME_URL] and page.closed


def test_navigation_error_sanitized_without_retry():
    result, page, _ = run_fake(pages={P1: RuntimeError("password=secret cookies=secret")})
    assert result.code == StopCode.NAVIGATION_FAILED and page.closed
    assert "secret" not in json.dumps(result.as_dict())
    assert page.calls == [HOME_URL, P1]


def test_images_and_media_are_not_retrieved_and_popup_is_blocked():
    page = FakePage()
    guard = NavigationGuard(page)
    for kind in ("image", "media"):
        route = FakeRoute(page.request("https://cdn.test/image", kind))
        guard.route(route)
        assert route.aborted and not route.continued
    popup = FakeRoute(page.request(P1, frame=SimpleNamespace(parent_frame=None)))
    guard.route(popup)
    assert popup.aborted and guard.stop_code == StopCode.UNEXPECTED_ROUTE


def test_guard_disallows_wrong_search_query_and_ports():
    page = FakePage()
    guard = NavigationGuard(page)
    guard.manual = False
    guard.expected = "https://shopee.tw/search?keyword=abc"
    assert guard.allowed(guard.expected)
    assert not guard.allowed(guard.expected + "&page=2")
    assert not guard.allowed("https://shopee.tw:443/search?keyword=abc")
    assert not guard.allowed("https://shopee.tw/search?keyword=def")


def test_manual_signin_only_permitted_before_collection():
    page = FakePage()
    page.pages[HOME_URL] = snapshot(login=True)
    page.pages[P1] = snapshot()
    def human_signs_in():
        page.pages[HOME_URL] = snapshot(login=False)
        return True
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=human_signs_in,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.COMPLETED


def test_still_on_login_route_after_confirmation_stops():
    page = FakePage()
    login_url = "https://shopee.tw/buyer/login"
    page.pages[login_url] = snapshot()
    def still_login():
        page.url = login_url
        return True
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=still_login,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.AUTH_REQUIRED and page.calls == [HOME_URL]


def test_cli_reads_request_file_with_bom_risk_ack_still_requires_manual_prompt(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"keyword": None, "urls": [P1], "max_items": 1, "interval_seconds": 60}), encoding="utf-8-sig")
    output = tmp_path / "result.json"
    prompts, logs = [], []
    page = FakePage({P1: snapshot()})
    def confirm(prompt):
        prompts.append(prompt)
        return "yes"
    code = run_cli(["--request", str(request), "--output", str(output), "--risk-acknowledged", "--channel", "msedge"],
                   input_fn=confirm, print_fn=logs.append, session_factory=FakeSession(page))
    data = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0 and data["source"] == SOURCE
    assert len(prompts) == 1 and "完成後" in prompts[0]
    assert "官方條款並沒有低頻率" in logs[0] and "帳號凍結" in logs[0]
    assert data["products"][0]["data_source"] == SOURCE
    assert page.closed


def test_cli_risk_declined_never_launches(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"urls": [P1]}), encoding="utf-8")
    session = FakeSession(FakePage())
    output = tmp_path / "result.json"
    code = run_cli(["--request", str(request), "--output", str(output)], input_fn=lambda _: "no",
                   print_fn=lambda _: None, session_factory=session)
    assert code != 0 and not session.entered
    assert json.loads(output.read_text())["result"]["code"] == "risk_declined"


def test_cli_invalid_input_does_not_launch_or_echo_request(tmp_path):
    request = tmp_path / "bad.json"
    request.write_text('{"cookie":"secret"}')
    logs = []
    session = FakeSession(FakePage())
    output = tmp_path / "result.json"
    code = run_cli(["--request", str(request), "--output", str(output)], print_fn=logs.append, session_factory=session)
    assert code != 0 and not session.entered
    assert "secret" not in "".join(logs) + output.read_text()


def test_output_preserves_partial_and_no_browser_artifacts(tmp_path):
    result = CollectionResult(products=[product_from_snapshot(snapshot(), P1)], code=StopCode.HTTP_BLOCKED)
    path = tmp_path / "result.json"
    write_result(path, result)
    data = json.loads(path.read_text())
    assert len(data["products"]) == 1 and data["result"]["code"] == "http_blocked"
    assert set(tmp_path.iterdir()) == {path}
    assert not {"cookies", "html", "screenshot", "storage_state"}.intersection(data)


# Tiny deterministic DOM implementation executes the actual extraction script,
# without a browser, network, npm installation, or external DOM dependency.
DOM_HARNESS = r"""
const fixture = JSON.parse(process.argv[1]);
class Element {
  constructor(props) { Object.assign(this, props); this.tagName = props.tag || 'DIV'; this.parentElement = null; }
  checkVisibility() { return !this.cssHidden; }
  contains(other) { for (let el = other; el; el = el.parentElement) { if (el === this) return true; } return false; }
  getBoundingClientRect() {
    global.rectOwner = this;
    return {width: this.hidden ? 0 : 100, height: 30, top: this.offscreen ? 1000 : 20,
            bottom: this.offscreen ? 1030 : 50, left: 0, right: 100};
  }
}
global.Element = Element;
global.innerHeight = 800; global.innerWidth = 1200;
global.getComputedStyle = el => ({display:'block',visibility:'visible',opacity:el.opacity ?? '1'});
global.NodeFilter = {SHOW_TEXT:4};
const elements = fixture.map(props => new Element(props));
elements.forEach((el, index) => {
  if (Number.isInteger(fixture[index].parent)) el.parentElement = elements[fixture[index].parent];
});
const texts = elements.filter(el => el.text || (el.tagName === 'H1' && el.innerText))
  .map(el => ({parentElement:el,textContent:el.text || el.innerText}));
global.document = {
  body: {},
  elementFromPoint: () => global.rectOwner.occluded ? new Element({}) : global.rectOwner,
  createTreeWalker: root => {
    const selected = root === document.body ? texts : texts.filter(node => root.contains(node.parentElement));
    let index = 0;
    return {nextNode: () => selected[index++] || null};
  },
  createRange: () => {
    let node;
    return {
      selectNodeContents: value => { node = value; },
      getClientRects: () => {
        const rect = node.parentElement.getBoundingClientRect();
        if (node.parentElement.textOffscreen) return [{...rect, top:1000, bottom:1030}];
        return [rect];
      }
    };
  },
  querySelectorAll: selector => {
    if (selector.startsWith('h1,')) return elements.filter(el => el.tagName === 'H1');
    if (selector === 'a[href]') return elements.filter(el => el.tagName === 'A');
    if (selector === 'input[type="password"]') return elements.filter(el => el.password);
    if (selector.startsWith('input[autocomplete')) return elements.filter(el => el.captcha);
    throw Error('Unexpected selector');
  }
};
const script = SCRIPT_PLACEHOLDER;
process.stdout.write(JSON.stringify(eval('(' + script + ')')({maxLinks:5})));
"""


def dom_snapshot(fixture):
    if not shutil.which("node"):
        pytest.skip("Node is optional for offline JavaScript DOM fixture tests")
    script = DOM_HARNESS.replace("SCRIPT_PLACEHOLDER", json.dumps(VISIBLE_SNAPSHOT_JS))
    completed = subprocess.run(["node", "-e", script, json.dumps(fixture)], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def test_actual_dom_excludes_hidden_offscreen_and_unmarked_currency():
    data = dom_snapshot([
        {"tag": "H1", "innerText": "可見商品"},
        {"tag": "H1", "innerText": "隱藏標題", "hidden": True},
        {"text": "NT$ 1,000"}, {"text": "NT$ 2,000", "hidden": True}, {"text": "$ 100"},
        {"tag": "A", "href": P1}, {"tag": "A", "href": P2, "offscreen": True},
        {"tag": "A", "href": P3, "hidden": True},
    ])
    assert data["titles"] == ["可見商品"]
    assert data["prices"] == ["NT$ 1,000"]
    assert data["links"] == [P1]


@pytest.mark.parametrize("fixture,flag", [
    ([{"text": "請完成安全驗證"}], "verification"),
    ([{"captcha": True}], "verification"),
    ([{"password": True}], "login"),
    ([{"text": "Too many requests"}], "blocked"),
    ([{"text": "您的帳號已凍結"}], "blocked"),
])
def test_actual_dom_safety_signals(fixture, flag):
    assert dom_snapshot(fixture)[flag] is True


def test_actual_dom_maximum_five_visible_links():
    fixture = [{"tag": "A", "href": f"https://shopee.tw/product/123/{i}"} for i in range(1, 9)]
    assert len(dom_snapshot(fixture)["links"]) == 5


def test_existing_output_is_unchanged_before_risk_prompt_or_browser(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"urls": [P1]}))
    output = tmp_path / "result.json"
    output.write_text("previous important result")
    session = FakeSession(FakePage())
    def must_not_prompt(_):
        pytest.fail("Must refuse existing output before asking or opening browser")
    code = run_cli(["--request", str(request), "--output", str(output)], input_fn=must_not_prompt,
                   print_fn=lambda _: None, session_factory=session)
    assert code != 0 and not session.entered
    assert output.read_text() == "previous important result"


def test_request_file_cannot_be_overwritten_as_output(tmp_path):
    request = tmp_path / "request.json"
    original = json.dumps({"urls": [P1]})
    request.write_text(original)
    session = FakeSession(FakePage())
    code = run_cli(["--request", str(request), "--output", str(request), "--risk-acknowledged"],
                   print_fn=lambda _: None, session_factory=session)
    assert code != 0 and not session.entered and request.read_text() == original


def test_output_race_never_overwrites_and_removes_temporary_file(tmp_path):
    output = tmp_path / "result.json"
    output.write_text("another writer")
    with pytest.raises(FileExistsError):
        write_result(output, CollectionResult())
    assert output.read_text() == "another writer"
    assert list(tmp_path.iterdir()) == [output]


def test_dangling_output_symlink_is_refused_before_launch(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"urls": [P1]}))
    output = tmp_path / "result.json"
    try:
        output.symlink_to(tmp_path / "missing")
    except OSError:
        pytest.skip("Test platform does not permit symlinks")
    session = FakeSession(FakePage())
    code = run_cli(["--request", str(request), "--output", str(output)], print_fn=lambda _: None,
                   session_factory=session)
    assert code != 0 and output.is_symlink() and not session.entered


@pytest.mark.parametrize("mode", ["search", "product"])
def test_bounded_render_wait_allows_delayed_client_dom_without_navigation_retry(mode):
    request = CollectionRequest(keyword="camera") if mode == "search" else CollectionRequest(urls=(P1,))
    target = request.search_url if mode == "search" else P1
    page = FakePage({target: snapshot(titles=[], prices=[], links=[]), P1: snapshot()})
    if mode == "product":
        page.pages[P1] = snapshot(titles=[], prices=[])
    def render(p):
        if p.url == target:
            p.pages[target] = snapshot(links=[P1])
    page.wait_callback = render
    result = collect(request, channel="chromium", confirm_manual=lambda: True, session_factory=FakeSession(page))
    assert result.code == StopCode.COMPLETED
    assert len(result.products) == 1 and page.calls.count(target) == 1
    assert page.waits.count(500) == 1


def test_bounded_render_wait_checks_captcha_before_readiness():
    page = FakePage({P1: snapshot(titles=[], prices=[])})
    def render_challenge(p):
        if p.url == P1:
            p.pages[P1] = snapshot(titles=[], prices=[], verification=True)
    page.wait_callback = render_challenge
    result = collect(CollectionRequest(urls=(P1, P2)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.VERIFICATION_REQUIRED
    assert page.calls == [HOME_URL, P1] and page.waits.count(500) == 1


def test_render_wait_is_bounded_then_stops_without_more_products():
    result, page, _ = run_fake(CollectionRequest(urls=(P1, P2)), {P1: snapshot(titles=[], prices=[])})
    assert result.code == StopCode.MISSING_TITLE
    assert page.waits.count(500) == 10
    assert page.calls == [HOME_URL, P1]


def test_verification_redirect_is_typed_and_stops_extraction():
    result, page, _ = run_fake(pages={P1: snapshot(redirect="https://shopee.tw/verify/captcha")})
    assert result.code == StopCode.VERIFICATION_REQUIRED
    assert page.calls == [HOME_URL, P1]


@pytest.mark.parametrize("kind", ["xhr", "fetch"])
def test_site_normal_background_response_status_latches_without_body_access(kind):
    page = FakePage()
    guard = NavigationGuard(page)
    response = SimpleNamespace(status=403, request=page.request("https://shopee.tw/normal-site-request", kind))
    guard.response(response)
    assert guard.stop_code == StopCode.HTTP_BLOCKED


def test_foreign_background_asset_status_does_not_latch():
    page = FakePage()
    guard = NavigationGuard(page)
    guard.response(SimpleNamespace(status=403, request=page.request("https://cdn.example/asset.js", "script")))
    assert guard.stop_code is None


def test_browser_startup_is_standard_headed_ephemeral_and_cleanup_runs_on_interrupt(monkeypatch):
    import sys
    from types import ModuleType
    from src.experimental.browser_collector import open_browser
    calls = []
    page = SimpleNamespace(
        set_default_timeout=lambda value: calls.append(("timeout", value)),
        set_default_navigation_timeout=lambda value: calls.append(("nav_timeout", value)),
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: calls.append(("context_close",)))
    def new_context(**kwargs):
        calls.append(("context", kwargs))
        return context
    browser = SimpleNamespace(new_context=new_context, close=lambda: calls.append(("browser_close",)))
    def launch(**kwargs):
        calls.append(("launch", kwargs))
        return browser
    @contextmanager
    def sync_playwright():
        try:
            yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        finally:
            calls.append(("playwright_close",))
    fake = ModuleType("playwright.sync_api")
    fake.sync_playwright = sync_playwright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    with pytest.raises(KeyboardInterrupt):
        with open_browser("msedge") as actual_page:
            assert actual_page is page
            raise KeyboardInterrupt
    assert ("launch", {"headless": False, "channel": "msedge"}) in calls
    assert ("context", {"accept_downloads": False, "service_workers": "block"}) in calls
    assert calls[-3:] == [("context_close",), ("browser_close",), ("playwright_close",)]


def test_browser_launch_failure_has_typed_result_without_raw_exception():
    @contextmanager
    def unavailable(_):
        raise CollectionStopped(StopCode.BROWSER_UNAVAILABLE)
        yield
    result = collect(CollectionRequest(urls=(P1,)), channel="msedge", confirm_manual=lambda: True,
                     session_factory=unavailable)
    assert result.code == StopCode.BROWSER_UNAVAILABLE and result.exit_code != 0


def test_cli_windows_defaults_to_edge_and_still_prompts_for_risk(tmp_path, monkeypatch):
    from src.experimental import browser_collector
    monkeypatch.setattr(browser_collector.sys, "platform", "win32")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"urls": [P1]}))
    session = FakeSession(FakePage({P1: snapshot()}))
    prompts = []
    def confirm(prompt):
        prompts.append(prompt)
        return "yes"
    code = run_cli(["--request", str(request), "--output", str(tmp_path / "result.json")], input_fn=confirm,
                   print_fn=lambda _: None, session_factory=session)
    assert code == 0 and session.channels == ["msedge"] and len(prompts) == 2


def test_login_reappearing_after_manual_confirmation_stops_before_navigation():
    page = FakePage({P1: snapshot()})
    def login_reappears(p):
        p.pages[HOME_URL] = snapshot(login=True)
    page.wait_callback = login_reappears
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.AUTH_REQUIRED
    assert page.calls == [HOME_URL] and len(page.waits) == 1 and page.closed


def test_manual_signin_returning_unexpected_account_route_stops():
    page = FakePage()
    account_url = "https://shopee.tw/user/account/profile"
    page.pages[account_url] = snapshot()
    def account_page():
        page.url = account_url
        return True
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=account_page,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.UNEXPECTED_ROUTE
    assert page.calls == [HOME_URL] and page.closed


def test_os_lock_refuses_second_contender_before_browser_and_then_releases(tmp_path):
    from src.experimental.browser_collector import collector_lock
    lock_path = tmp_path / "collector.lock"
    page = FakePage({P1: snapshot()})
    session = FakeSession(page)
    factory = lambda: collector_lock(lock_path)
    with collector_lock(lock_path):
        result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                         session_factory=session, lock_factory=factory)
        assert result.code == StopCode.ALREADY_RUNNING
        assert not session.entered and not page.calls
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=session, lock_factory=factory)
    assert result.code == StopCode.COMPLETED and page.closed
    assert lock_path.read_bytes() == b"\0"


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), RuntimeError("browser error")])
def test_os_lock_released_after_cancellation_or_failure(tmp_path, failure):
    from src.experimental.browser_collector import collector_lock
    lock_path = tmp_path / "collector.lock"
    page = FakePage({P1: failure})
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=lambda: True,
                     session_factory=FakeSession(page), lock_factory=lambda: collector_lock(lock_path))
    assert result.exit_code != 0 and page.closed
    with collector_lock(lock_path):
        pass
    assert lock_path.read_bytes() == b"\0"


def test_os_lock_never_overwrites_arbitrary_existing_file(tmp_path):
    from src.experimental.browser_collector import collector_lock
    lock_path = tmp_path / "collector.lock"
    lock_path.write_text("Important existing file")
    with pytest.raises(CollectionStopped) as error:
        with collector_lock(lock_path):
            pytest.fail("Must not acquire malformed existing file")
    assert error.value.code == StopCode.LOCK_UNAVAILABLE
    assert lock_path.read_text() == "Important existing file"


def test_os_lock_refuses_symlink_without_altering_target(tmp_path):
    from src.experimental.browser_collector import collector_lock
    target = tmp_path / "target"
    target.write_bytes(b"\0")
    lock_path = tmp_path / "collector.lock"
    try:
        lock_path.symlink_to(target)
    except OSError:
        pytest.skip("Test platform does not permit symlinks")
    with pytest.raises(CollectionStopped) as error:
        with collector_lock(lock_path):
            pytest.fail("Must not acquire through a symlink")
    assert error.value.code == StopCode.LOCK_UNAVAILABLE
    assert target.read_bytes() == b"\0" and lock_path.is_symlink()


def test_os_lock_is_cross_process_and_survives_clean_exit(tmp_path):
    import sys
    from src.experimental.browser_collector import collector_lock
    lock_path = tmp_path / "collector.lock"
    script = (
        "from pathlib import Path; import sys; "
        "from src.experimental.browser_collector import collector_lock, CollectionStopped; "
        "path=Path(sys.argv[1]); "
        "\ntry:\n with collector_lock(path): print('acquired')"
        "\nexcept CollectionStopped as exc: print(exc.code.value)"
    )
    with collector_lock(lock_path):
        contender = subprocess.run([sys.executable, "-c", script, str(lock_path)], text=True,
                                   capture_output=True, check=True)
        assert contender.stdout.strip() == "already_running"
    successor = subprocess.run([sys.executable, "-c", script, str(lock_path)], text=True,
                               capture_output=True, check=True)
    assert successor.stdout.strip() == "acquired"


def test_manual_prompt_keeps_dispatching_on_main_thread_until_human_answer():
    import threading
    main_thread = threading.get_ident()
    page = FakePage({P1: snapshot()})
    event_serviced = threading.Event()
    observed = []
    def terminal_wait():
        observed.append(("terminal", threading.get_ident()))
        assert event_serviced.wait(timeout=2), "Browser dispatcher stalled behind input"
        return True
    def dispatch_signin(p):
        if not event_serviced.is_set():
            observed.append(("dispatcher", threading.get_ident()))
            event_serviced.set()
    page.wait_callback = dispatch_signin
    result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=terminal_wait,
                     session_factory=FakeSession(page))
    assert result.code == StopCode.COMPLETED
    assert ("dispatcher", main_thread) in observed
    assert next(identity for label, identity in observed if label == "terminal") != main_thread
    assert 100 in page.waits and page.closed


def test_challenge_during_pending_manual_input_stops_and_releases_lock(tmp_path):
    import threading
    from src.experimental.browser_collector import collector_lock
    lock_path = tmp_path / "collector.lock"
    page = FakePage({P1: snapshot()})
    release_terminal = threading.Event()
    def terminal_wait():
        release_terminal.wait(timeout=2)
        return True
    def challenge(p):
        p.pages[HOME_URL] = snapshot(verification=True)
    page.wait_callback = challenge
    try:
        result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=terminal_wait,
                         session_factory=FakeSession(page), lock_factory=lambda: collector_lock(lock_path))
        assert result.code == StopCode.VERIFICATION_REQUIRED
        assert page.calls == [HOME_URL] and page.closed
        assert not release_terminal.is_set()
        with collector_lock(lock_path):
            pass
    finally:
        release_terminal.set()


def test_cancel_during_pending_manual_input_closes_browser():
    import threading
    page = FakePage({P1: snapshot()})
    release_terminal = threading.Event()
    cancel = threading.Event()
    page.wait_callback = lambda _: cancel.set()
    def terminal_wait():
        release_terminal.wait(timeout=2)
        return True
    try:
        result = collect(CollectionRequest(urls=(P1,)), channel="chromium", confirm_manual=terminal_wait,
                         session_factory=FakeSession(page), cancelled=cancel.is_set)
        assert result.code == StopCode.CANCELLED
        assert page.calls == [HOME_URL] and page.closed
    finally:
        release_terminal.set()


def test_actual_dom_rejects_occluded_and_css_hidden_links_prices_and_titles():
    data = dom_snapshot([
        {"tag": "H1", "innerText": "可見商品"},
        {"tag": "H1", "innerText": "被遮住的標題", "occluded": True},
        {"text": "NT$ 1,000"}, {"text": "NT$ 2,000", "cssHidden": True},
        {"tag": "A", "href": P1}, {"tag": "A", "href": P2, "occluded": True},
        {"tag": "A", "href": P3, "cssHidden": True},
    ])
    assert data["titles"] == ["可見商品"]
    assert data["prices"] == ["NT$ 1,000"]
    assert data["links"] == [P1]


def test_browser_oserror_is_not_misreported_as_lock_failure():
    result, page, _ = run_fake(pages={P1: OSError("navigation socket closed")})
    assert result.code == StopCode.NAVIGATION_FAILED and page.closed


def test_same_product_http_redirect_also_stops_without_extraction():
    result, page, _ = run_fake(pages={P1: snapshot(redirect=P1 + "?tracking=redirect")})
    assert result.code == StopCode.REDIRECT_DETECTED
    assert result.products == [] and page.evaluations.count(P1) == 0
    assert page.network_urls == [HOME_URL, P1, P1 + "?tracking=redirect"]


def test_external_then_allowed_redirect_chain_cannot_hide_external_hop():
    external = "https://external.example/hop"
    result, page, _ = run_fake(CollectionRequest(urls=(P1, P2)),
                               {P1: snapshot(redirect_chain=[external, P1]), P2: snapshot()})
    assert result.code == StopCode.UNEXPECTED_ROUTE
    assert result.products == [] and page.calls == [HOME_URL, P1]
    # Do not pretend route interception prevented an HTTP redirect request.
    assert page.network_urls == [HOME_URL, P1, external, P1]
    assert P1 not in page.evaluations and page.closed


def test_final_response_ancestry_catches_missed_intermediate_events():
    page = FakePage()
    guard = NavigationGuard(page)
    guard.manual = False
    guard.expected = P1
    original = page.request(P1)
    external = page.request("https://external.example/hop")
    external.redirected_from = original
    final = page.request(P1)
    final.redirected_from = external
    guard.response(SimpleNamespace(status=200, url=P1, request=final))
    assert guard.stop_code == StopCode.REDIRECT_DETECTED
    with pytest.raises(CollectionStopped):
        guard.check()


def test_response_actual_url_checked_even_if_final_page_url_looks_allowed():
    page = FakePage()
    page.url = P1
    guard = NavigationGuard(page)
    guard.manual = False
    guard.expected = P1
    guard.response(SimpleNamespace(status=200, url="https://external.example/hop", request=page.request(P1)))
    assert guard.stop_code == StopCode.UNEXPECTED_ROUTE


def test_manual_same_host_login_redirect_allowed_but_external_is_latched():
    page = FakePage()
    guard = NavigationGuard(page)
    request = page.request(HOME_URL)
    guard.response(SimpleNamespace(status=302, url=HOME_URL, request=request,
                                   header_value=lambda _: "https://shopee.tw/buyer/login"))
    assert guard.stop_code is None
    guard.response(SimpleNamespace(status=302, url=HOME_URL, request=request,
                                   header_value=lambda _: "https://external.example/login"))
    assert guard.stop_code == StopCode.UNEXPECTED_ROUTE


def test_actual_dom_bare_currency_never_uses_offscreen_sibling_amount():
    data = dom_snapshot([
        {"tag": "H1", "innerText": "可見商品"},
        {"innerText": "NT$ 999"},
        {"text": "NT$", "parent": 1},
        {"text": "999", "offscreen": True, "parent": 1},
    ])
    assert data["titles"] == ["可見商品"]
    assert data["prices"] == ["NT$"]
    assert "999" not in json.dumps(data)
    with pytest.raises(CollectionStopped) as error:
        product_from_snapshot(data, P1)
    assert error.value.code == StopCode.AMBIGUOUS_PRICE


def test_actual_dom_mixed_visible_offscreen_heading_fails_closed():
    data = dom_snapshot([
        {"tag": "H1", "text": "可見", "innerText": "可見隱藏標題"},
        {"text": "隱藏標題", "offscreen": True, "parent": 0},
        {"text": "NT$ 999"},
    ])
    assert data["titles"] == []
    assert "隱藏標題" not in json.dumps(data, ensure_ascii=False)
    with pytest.raises(CollectionStopped) as error:
        product_from_snapshot(data, P1)
    assert error.value.code == StopCode.MISSING_TITLE


def test_actual_dom_text_range_not_visible_ancestor_controls_extraction():
    data = dom_snapshot([
        {"tag": "H1", "innerText": "可見商品"},
        {"text": "NT$ 999", "textOffscreen": True},
    ])
    assert data["prices"] == []
    with pytest.raises(CollectionStopped) as error:
        product_from_snapshot(data, P1)
    assert error.value.code == StopCode.MISSING_PRICE


def test_actual_dom_heading_composes_only_independently_visible_text_nodes():
    data = dom_snapshot([
        {"tag": "H1", "text": "可見", "innerText": "Do not read this aggregate"},
        {"text": "商品", "parent": 0},
        {"text": "NT$ 999"},
    ])
    assert data["titles"] == ["可見商品"]
    assert product_from_snapshot(data, P1)["title"] == "可見商品"


def test_manual_challenge_location_latches_even_when_redirect_returns_home():
    page = FakePage()
    guard = NavigationGuard(page)
    request = page.request(HOME_URL)
    guard.response(SimpleNamespace(status=302, url=HOME_URL, request=request,
                                   header_value=lambda _: "https://shopee.tw/verify/captcha"))
    assert guard.stop_code == StopCode.VERIFICATION_REQUIRED
    guard.response(SimpleNamespace(status=200, url=HOME_URL, request=request))
    assert guard.stop_code == StopCode.VERIFICATION_REQUIRED


def test_manual_challenge_actual_response_url_latches_before_home():
    page = FakePage()
    guard = NavigationGuard(page)
    challenge = "https://shopee.tw/verify/captcha"
    guard.response(SimpleNamespace(status=200, url=challenge, request=page.request(challenge)))
    guard.response(SimpleNamespace(status=200, url=HOME_URL, request=page.request(HOME_URL)))
    assert guard.stop_code == StopCode.VERIFICATION_REQUIRED


def test_manual_final_response_ancestry_preserves_vanished_challenge():
    page = FakePage()
    guard = NavigationGuard(page)
    original = page.request(HOME_URL)
    challenge = page.request("https://shopee.tw/verify/captcha")
    challenge.redirected_from = original
    final = page.request(HOME_URL)
    final.redirected_from = challenge
    guard.response(SimpleNamespace(status=200, url=HOME_URL, request=final))
    assert guard.stop_code == StopCode.VERIFICATION_REQUIRED


def test_manual_direct_challenge_route_is_aborted():
    page = FakePage()
    guard = NavigationGuard(page)
    route = FakeRoute(page.request("https://shopee.tw/verify/captcha"))
    guard.route(route)
    assert route.aborted and guard.stop_code == StopCode.VERIFICATION_REQUIRED
