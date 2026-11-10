"""CSV 輸出與 Webhook 傳送。"""
import csv
import io
from typing import Optional

import requests

from .extract import FIELDS

BASE_COLUMNS = [
    "搜尋關鍵字", "品名", "狀態", "記憶體", "儲存容量", "保固", "購買日期",
    "價格", "多規格最高價", "出貨地", "賣場", "已售", "上架日期", "商品連結", "資料來源",
]
AI_PREFIX = "AI_"


def columns_for(mode: str) -> list[str]:
    if mode == "compare":
        return BASE_COLUMNS + [AI_PREFIX + f for f in FIELDS] + ["差異欄位"]
    return BASE_COLUMNS


def build_csv(rows: list[dict], mode: str = "off") -> bytes:
    """回傳帶 UTF-8 BOM 的 CSV，Excel 直接雙擊就能正確顯示中文。"""
    columns = columns_for(mode)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def send_csv_webhook(
    url: str,
    csv_bytes: bytes,
    filename: str,
    message: str,
    proxy: str = "",
) -> str:
    """把 CSV 當附件用 multipart 傳到 Webhook。Discord 與一般接受檔案上傳的 Webhook 都可用。"""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Webhook 網址必須以 http:// 或 https:// 開頭")
    proxies: Optional[dict] = {"http": proxy, "https": proxy} if proxy else None
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        data = {"content": message}
        files = {"files[0]": (filename, csv_bytes, "text/csv")}
    else:
        data = {"content": message, "text": message}
        files = {"file": (filename, csv_bytes, "text/csv")}
    response = requests.post(url, data=data, files=files, timeout=60, proxies=proxies)
    response.raise_for_status()
    return f"已傳送（HTTP {response.status_code}）"
