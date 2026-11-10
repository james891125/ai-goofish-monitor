"""把「搜尋 → 規則抽欄位 →（選用）補詳情 →（選用）AI」串成一個流程，輸出 CSV 用的資料列。"""
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import shopee
from .ai import AIClient, enrich_rows
from .errors import LoginRequiredError, RiskControlError
from .extract import FIELDS, extract_fields

DETAIL_MODES = ("off", "auto", "all")
# 搜尋主機時常混進大量配件；標題含這些詞的商品預設不列入
ACCESSORY_WORDS = (
    "保護貼", "保護殼", "保護套", "保護膜", "保護框", "鋼化膜", "玻璃貼", "貼膜", "螢幕貼", "滿版貼",
    "錶帶", "表帶", "錶鏈", "表鏈", "手錶殼", "矽膠套", "外殼", "吊墜", "充電線", "充電器", "充電座", "充電盤", "傳輸線",
    "轉接頭", "轉接線", "轉接器", "支架", "底座", "擴充基座", "外接盒", "開機鍵", "電源鍵", "供電套件", "外框架", "機箱", "散熱器", "散熱座", "散熱墊",
    "拓展塢", "擴展塢", "擴充座", "擴充外接", "集線器", "硬碟盒", "收納", "防塵", "腳墊", "貼紙",
    "代購金", "已售出", "已售完",
)


def is_accessory(title: str) -> bool:
    lowered = str(title).lower()
    return any(word in lowered for word in ACCESSORY_WORDS)


def parse_words(text) -> list[str]:
    """把「殼, 膜 線」這種輸入拆成詞清單（逗號、頓號、空白、換行都可分隔）。"""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text)
    return [w for w in re.split(r"[,，、\s]+", str(text or "")) if w]


def _to_number(value) -> Optional[float]:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def price_in_range(item: dict, min_price, max_price) -> bool:
    """本機再檢查一次價格：蝦皮的價格篩選對多規格商品不精確，配件常靠最低價規格混進來。"""
    low, _ = parse_price_range(item.get("目前售價"))
    if low is None:
        return True
    floor, ceiling = _to_number(min_price), _to_number(max_price)
    if floor is not None and low < floor:
        return False
    return not (ceiling is not None and low > ceiling)

AI_MODES = ("off", "on", "compare")
MAX_PAGES = 10
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class RunOptions:
    keywords: list[str]
    pages: int = 3
    min_price: str = ""
    max_price: str = ""
    latest: bool = False
    region: str = ""
    free_shipping: bool = False
    detail: str = "auto"
    ai: str = "off"
    title_match: bool = True
    exclude_accessories: bool = True
    extra_exclude: list[str] = field(default_factory=list)
    page_pause: tuple[float, float] = (5, 10)
    detail_pause: tuple[float, float] = (3, 6)

    def validate(self) -> None:
        self.keywords = [k.strip() for k in self.keywords if k and k.strip()]
        if not self.keywords:
            raise ValueError("請至少輸入一個關鍵字。")
        if self.detail not in DETAIL_MODES:
            raise ValueError(f"detail 只能是 {', '.join(DETAIL_MODES)}")
        if self.ai not in AI_MODES:
            raise ValueError(f"ai 只能是 {', '.join(AI_MODES)}")
        self.pages = max(1, min(int(self.pages), MAX_PAGES))


@dataclass
class RunResult:
    rows: list[dict] = field(default_factory=list)
    mode: str = "off"
    summary: list[str] = field(default_factory=list)


def parse_price_range(text: str) -> tuple[Optional[int], Optional[int]]:
    numbers = [float(n.replace(",", "")) for n in _NUMBER.findall(str(text or ""))]
    if not numbers:
        return None, None
    return int(min(numbers)), int(max(numbers))


def _needs_detail(fields: dict) -> bool:
    return not fields["狀態"] or (not fields["記憶體"] and not fields["儲存容量"])


def _make_row(keyword: str, item: dict) -> dict:
    low, high = parse_price_range(item.get("目前售價"))
    fields = extract_fields(item["商品標題"])
    row = {
        "搜尋關鍵字": keyword,
        "品名": item["商品標題"],
        **fields,
        "價格": low if low is not None else "",
        "多規格最高價": high if high is not None and high != low else "",
        "出貨地": item.get("出貨地區", ""),
        "賣場": item.get("賣家暱稱", ""),
        "已售": item.get("已售數量", ""),
        "上架日期": item.get("釋出時間", ""),
        "商品連結": item.get("商品連結", ""),
        "資料來源": "標題",
        "_描述": "",
        "_id": item.get("商品ID"),
        "_item": item,
    }
    return row


def _apply_detail(row: dict, payload: dict) -> None:
    detail = shopee.parse_item_detail(payload)
    description = str(detail.get("商品描述") or "")
    attrs = detail.get("商品屬性") or {}
    attr_text = " ".join(f"{k}:{v}" for k, v in attrs.items())
    row["_描述"] = (description + " " + attr_text).strip()
    # 描述只用來補空白欄位，而且不拿來判斷「故障／預購」（制式文字容易誤判）
    merged = extract_fields(row["_描述"], from_description=True)
    for name in FIELDS:
        if not row[name] and merged[name]:
            row[name] = merged[name]
    if row["價格"] == "" and detail.get("目前售價"):
        low, high = parse_price_range(detail["目前售價"])
        row["價格"] = low if low is not None else ""
        row["多規格最高價"] = high if high is not None and high != low else ""
    row["資料來源"] = "標題+詳情頁"


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def values_agree(name: str, rule_value: str, ai_value: str) -> bool:
    a, b = _norm(rule_value), _norm(ai_value)
    if a == b:
        return True
    if not a or not b:
        return False
    if name == "保固":
        if a in b or b in a:
            return True
        return re.findall(r"\d+", a) == re.findall(r"\d+", b)
    if name == "規格":
        split = lambda v: {t for t in re.split(r"[、,，/／\s]+", v) if t}  # noqa: E731
        return split(a) == split(b)
    return False


def merge_ai(rows: list[dict], mode: str) -> list[str]:
    """on：規則為主、AI 只補空白；compare：兩邊並排並標出差異。回傳統計摘要。"""
    stats = {name: {"rule": 0, "ai": 0, "same": 0, "diff": 0, "only_ai": 0, "only_rule": 0} for name in FIELDS}
    answered = 0
    for row in rows:
        ai_fields = row.get("_AI")
        if ai_fields is None:
            continue
        answered += 1
        diffs = []
        for name in FIELDS:
            rule_value, ai_value = row[name], ai_fields.get(name, "")
            s = stats[name]
            s["rule"] += bool(rule_value)
            s["ai"] += bool(ai_value)
            if values_agree(name, rule_value, ai_value):
                s["same"] += 1
            else:
                s["diff"] += 1
                if ai_value and not rule_value:
                    s["only_ai"] += 1
                elif rule_value and not ai_value:
                    s["only_rule"] += 1
                diffs.append(name)
            if mode == "compare":
                row["AI_" + name] = ai_value
            elif mode == "on" and not rule_value and ai_value:
                row[name] = ai_value
        if mode == "compare":
            row["差異欄位"] = "、".join(diffs)
        if mode == "on":
            row["資料來源"] += "+AI"
    lines = [f"AI 回覆了 {answered}/{len(rows)} 件商品"]
    if answered:
        lines.append("欄位　　規則有值　AI有值　一致　不同（只有AI有／只有規則有）")
        for name in FIELDS:
            s = stats[name]
            lines.append(
                f"{name}　{s['rule']}　{s['ai']}　{s['same']}　{s['diff']}（{s['only_ai']}／{s['only_rule']}）"
            )
    return lines


async def run_search(
    options: RunOptions,
    browser,
    ai_client: Optional[AIClient],
    log: Callable[[str], None] = print,
    should_stop: Optional[Callable[[], bool]] = None,
) -> RunResult:
    options.validate()
    stop = should_stop or (lambda: False)
    rows: list[dict] = []
    seen: set[str] = set()
    extra_words = [w.lower() for w in parse_words(options.extra_exclude)]

    for keyword in options.keywords:
        for page_num in range(1, options.pages + 1):
            if stop():
                break
            url = shopee.build_search_url(
                keyword,
                page=page_num - 1,
                min_price=options.min_price,
                max_price=options.max_price,
                sort_by_latest=options.latest,
            )
            log(f"「{keyword}」第 {page_num}/{options.pages} 頁...")
            payload = await browser.search(url)
            items = shopee.parse_search_items(payload)
            if not items:
                log("這一頁沒有商品，停止翻頁。")
                break
            total = len(items)
            items = shopee.filter_search_items(
                items, free_shipping=options.free_shipping, region_filter=options.region
            )
            if options.title_match:
                items = [i for i in items if shopee.title_matches_keyword(i["商品標題"], keyword)]
            if options.exclude_accessories:
                items = [i for i in items if not is_accessory(i["商品標題"])]
            if extra_words:
                items = [
                    i for i in items
                    if not any(w in i["商品標題"].lower() for w in extra_words)
                ]
            items = [i for i in items if price_in_range(i, options.min_price, options.max_price)]
            added = 0
            for item in items:
                item_id = str(item.get("商品ID"))
                if item_id in seen:
                    continue
                seen.add(item_id)
                rows.append(_make_row(keyword, item))
                added += 1
            log(f"  讀到 {total} 件，留下 {added} 件（累計 {len(rows)} 件）。")
            if page_num < options.pages and not stop():
                await browser.pause(*options.page_pause)

    if options.detail != "off" and rows and not stop():
        targets = [r for r in rows if options.detail == "all" or _needs_detail(r)]
        log(f"標題資訊不足、需要補抓詳情頁的商品：{len(targets)} 件。")
        for index, row in enumerate(targets, 1):
            if stop():
                break
            log(f"  詳情 {index}/{len(targets)}: {row['品名'][:30]}")
            try:
                payload = await browser.detail(row["商品連結"])
            except RiskControlError:
                log("詳情頁被蝦皮攔截，剩下的商品只用標題資料。")
                break
            except LoginRequiredError:
                raise
            except Exception as exc:  # noqa: BLE001 - 單件失敗不影響整體
                log(f"  這件抓不到詳情，改用標題資料: {exc}")
                payload = None
            if payload:
                _apply_detail(row, payload)
            if index < len(targets):
                await browser.pause(*options.detail_pause)

    result = RunResult(rows=rows, mode="off")
    if options.ai != "off" and rows and not stop():
        if ai_client is None or not ai_client.is_ready():
            result.summary.append("尚未設定 AI（API Key），已略過 AI 步驟。")
        else:
            await enrich_rows(ai_client, rows, log, stop)
            result.mode = options.ai
            result.summary += merge_ai(rows, options.ai)
            result.summary.append(ai_client.usage.summary())
    return result
