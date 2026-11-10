"""
用規則從商品標題（與描述）抽出：狀態、記憶體、儲存容量、保固、購買日期。

全部是純函式，不需要 AI 也不需要網路。抓不到就回傳空字串，絕不猜測。
容量的判斷是啟發式：同時出現兩個容量時，較小的當記憶體、較大的當儲存空間。
"""
import re

FIELDS = ("狀態", "記憶體", "儲存容量", "保固", "購買日期")
CONDITIONS = ("全新", "近全新", "二手", "福利品", "展示機", "故障/零件機", "預購")

_BROKEN = ("故障", "零件機", "無法開機", "不能開機", "殺肉", "拆零件", "維修用")
_PREORDER = ("預購", "預訂", "訂金")
_REFURB = ("福利品", "整新品", "整新機", "認證整修")
_DISPLAY = ("展示機", "展示品", "展售機")
_NEAR_NEW = (
    "近全新", "接近全新", "幾乎全新", "如新", "極新", "極美", "9成新", "九成新",
    "99新", "9.9成新", "95新", "9成9新", "九成九新", "美品",
)
_USED = ("二手", "中古", "使用過", "已拆封", "拆封過")
_NEW = ("全新", "未拆", "未開封", "新品", "未使用")
_NOT_NEW = ("非全新", "不是全新", "並非全新")


def _has(text: str, words) -> bool:
    return any(word in text for word in words)


def extract_condition(text: str) -> str:
    lowered = text.lower()
    if _has(lowered, _BROKEN):
        return "故障/零件機"
    if _has(lowered, _PREORDER):
        return "預購"
    if _has(lowered, _REFURB):
        return "福利品"
    if _has(lowered, _DISPLAY):
        return "展示機"
    if _has(lowered, _NEAR_NEW):
        return "近全新"
    if _has(lowered, _NOT_NEW) or _has(lowered, _USED):
        return "二手"
    if _has(lowered, _NEW):
        return "全新"
    return ""


_UNIT = r"(TB|T|GB|G)(?![A-Za-z])"
_SIZE = re.compile(rf"(\d+(?:\.\d+)?)\s*{_UNIT}", re.IGNORECASE)
_PLUS = re.compile(rf"(\d{{1,3}})\s*\+\s*(\d+(?:\.\d+)?)\s*{_UNIT}", re.IGNORECASE)
_MEM_AFTER = re.compile(r"(\d+)\s*(?:GB|G)\s*(?:RAM|記憶體|統一記憶體)", re.IGNORECASE)
_MEM_BEFORE = re.compile(r"(?:RAM|記憶體|統一記憶體)\s*[:：]?\s*(\d+)\s*(?:GB|G)(?![A-Za-z])", re.IGNORECASE)
_STORE_AFTER = re.compile(
    rf"(\d+(?:\.\d+)?)\s*{_UNIT}\s*(?:SSD|HDD|NVMe|M\.2|硬碟|固態|儲存)", re.IGNORECASE
)
_STORE_BEFORE = re.compile(
    rf"(?:SSD|HDD|硬碟|儲存空間|儲存容量|容量)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*{_UNIT}", re.IGNORECASE
)
_MIN_GB = 2
_MAX_GB = 16384
_STORAGE_FLOOR_GB = 128


def _to_gb(number: str, unit: str) -> float:
    value = float(number)
    return value * 1024 if unit.upper().startswith("T") else value


def format_size(gb: float) -> str:
    if gb >= 1024 and abs(gb / 1024 - round(gb / 1024)) < 0.01:
        return f"{int(round(gb / 1024))}TB"
    if gb >= 1024:
        return f"{gb / 1024:.1f}TB"
    return f"{int(gb) if float(gb).is_integer() else gb}GB"


def extract_capacity(text: str) -> tuple[str, str]:
    """回傳 (記憶體, 儲存容量)，抓不到的那一項是空字串。"""
    memory_gb = None
    storage_gb = None

    plus = _PLUS.search(text)
    if plus:
        memory_candidate = float(plus.group(1))
        storage_candidate = _to_gb(plus.group(2), plus.group(3))
        if memory_candidate <= 128 and storage_candidate >= memory_candidate:
            memory_gb, storage_gb = memory_candidate, storage_candidate

    if memory_gb is None:
        match = _MEM_AFTER.search(text) or _MEM_BEFORE.search(text)
        if match:
            memory_gb = float(match.group(1))
    if storage_gb is None:
        match = _STORE_AFTER.search(text)
        if match:
            storage_gb = _to_gb(match.group(1), match.group(2))
        else:
            match = _STORE_BEFORE.search(text)
            if match:
                storage_gb = _to_gb(match.group(1), match.group(2))

    if memory_gb is None or storage_gb is None:
        sizes = []
        for found in _SIZE.finditer(text):
            gb = _to_gb(found.group(1), found.group(2))
            # 5G 是行動網路世代，不是容量
            if gb == 5 or text[found.end():found.end() + 3] in ("網路", "網絡", "行動", "訊號"):
                continue
            if _MIN_GB <= gb <= _MAX_GB and gb not in (memory_gb, storage_gb):
                sizes.append(gb)
        sizes = sorted(set(sizes))
        if memory_gb is None and storage_gb is None:
            if len(sizes) >= 2 and sizes[0] <= 128 and sizes[-1] > sizes[0]:
                memory_gb, storage_gb = sizes[0], sizes[-1]
            elif len(sizes) == 1:
                if sizes[0] >= _STORAGE_FLOOR_GB:
                    storage_gb = sizes[0]
                else:
                    memory_gb = sizes[0]
        elif memory_gb is None and sizes:
            smaller = [s for s in sizes if s <= 128]
            if smaller:
                memory_gb = smaller[0]
        elif storage_gb is None and sizes:
            larger = [s for s in sizes if s >= _STORAGE_FLOOR_GB and s != memory_gb]
            if larger:
                storage_gb = larger[-1]

    return (
        format_size(memory_gb) if memory_gb else "",
        format_size(storage_gb) if storage_gb else "",
    )


_DATE = r"(20\d{2})\s*[/\-.年]\s*(\d{1,2})(?:\s*[/\-.月]\s*(\d{1,2}))?"


def _fmt_date(year: str, month: str, day: str | None) -> str:
    text = f"{year}/{int(month):02d}"
    return f"{text}/{int(day):02d}" if day else text


_WARRANTY_UNTIL = re.compile(rf"保固\s*(?:到|至|期至|期限|截止)?\s*[:：]?\s*{_DATE}")
_WARRANTY_UNTIL_AFTER = re.compile(rf"{_DATE}\s*(?:止|前|到期)\s*(?:的)?\s*保固")
_WARRANTY_SPAN = re.compile(r"(?:保固\s*[:：]?\s*(\d+|[一二三兩])\s*(年|個月|月)|(\d+|[一二三兩])\s*(年|個月)\s*(?:原廠|店保|商店|賣場)?保固)")
_ZH_NUM = {"一": "1", "二": "2", "兩": "2", "三": "3"}
_WARRANTY_EXPIRED = ("過保", "已過保", "保固已過", "無保固", "沒有保固", "沒保固", "保固已到期", "保固到期")
_WARRANTY_ACTIVE = ("保固中", "保內", "保固內", "原廠保固", "有保固", "含保固", "公司貨保固", "保固期內", "享保固")


def extract_warranty(text: str) -> str:
    match = _WARRANTY_UNTIL.search(text) or _WARRANTY_UNTIL_AFTER.search(text)
    if match:
        return f"保固至 {_fmt_date(*match.groups()[:3])}"
    if _has(text, _WARRANTY_EXPIRED):
        return "已過保/無保固"
    span = _WARRANTY_SPAN.search(text)
    if span:
        number = span.group(1) or span.group(3)
        unit = span.group(2) or span.group(4)
        number = _ZH_NUM.get(number, number)
        return f"保固 {number} {'年' if unit == '年' else '個月'}"
    if _has(text, _WARRANTY_ACTIVE):
        return "保固中"
    return ""


_PURCHASE_KEYS = (
    "購買日期", "購入日期", "購買時間", "購入時間", "購買於", "購於", "購入於", "購入", "購買",
    "發票日期", "發票日", "出廠日期", "生產日期", "啟用日期", "入手",
)
_PURCHASE_BEFORE = re.compile(rf"(?:{'|'.join(_PURCHASE_KEYS)})\s*[:：]?\s*{_DATE}")
_PURCHASE_AFTER = re.compile(rf"{_DATE}\s*日?\s*(?:購入|購買|購於|入手|買的|發票)")


def extract_purchase_date(text: str) -> str:
    """只有文字明確寫出購買／發票日期才回傳；上架日期不等於購買日期。"""
    match = _PURCHASE_BEFORE.search(text) or _PURCHASE_AFTER.search(text)
    if not match:
        return ""
    return _fmt_date(*match.groups()[:3])


def extract_fields(text: str) -> dict:
    memory, storage = extract_capacity(text)
    return {
        "狀態": extract_condition(text),
        "記憶體": memory,
        "儲存容量": storage,
        "保固": extract_warranty(text),
        "購買日期": extract_purchase_date(text),
    }
