import asyncio
import json
import math
import os
import random
import re
import glob
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from openai import APIStatusError
from requests.exceptions import HTTPError

from src.services.result_storage_service import save_result_record


def retry_on_failure(retries=3, delay=5):
    """
    一個通用的非同步重試裝飾器，增加了對HTTP錯誤的詳細日誌記錄。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (APIStatusError, HTTPError) as e:
                    print(f"函式 {func.__name__} 第 {i + 1}/{retries} 次嘗試失敗，發生HTTP錯誤。")
                    if hasattr(e, 'status_code'):
                        print(f"  - 狀態碼 (Status Code): {e.status_code}")
                    if hasattr(e, 'response') and hasattr(e.response, 'text'):
                        response_text = e.response.text
                        print(
                            f"  - 返回值 (Response): {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
                except json.JSONDecodeError as e:
                    print(f"函式 {func.__name__} 第 {i + 1}/{retries} 次嘗試失敗: JSON解析錯誤 - {e}")
                except Exception as e:
                    print(f"函式 {func.__name__} 第 {i + 1}/{retries} 次嘗試失敗: {type(e).__name__} - {e}")

                if i < retries - 1:
                    print(f"將在 {delay} 秒後重試...")
                    await asyncio.sleep(delay)

            print(f"函式 {func.__name__} 在 {retries} 次嘗試後徹底失敗。")
            return None
        return wrapper
    return decorator


async def safe_get(data, *keys, default="暫無"):
    """安全獲取巢狀字典值"""
    for key in keys:
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            return default
    return data


async def random_sleep(min_seconds: float, max_seconds: float):
    """非同步等待一個在指定範圍內的隨機時間。"""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"   [延遲] 等待 {delay:.2f} 秒... (範圍: {min_seconds}-{max_seconds}s)")
    await asyncio.sleep(delay)


def log_time(message: str, prefix: str = "") -> None:
    """在日誌前加上 YY-MM-DD HH:MM:SS 時間戳的簡單列印。"""
    try:
        ts = datetime.now().strftime(' %Y-%m-%d %H:%M:%S')
    except Exception:
        ts = "--:--:--"
    print(f"[{ts}] {prefix}{message}")


def sanitize_filename(value: str) -> str:
    """生成安全的檔名片段。"""
    if not value:
        return "task"
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "task"


def build_task_log_path(task_id: int, task_name: str) -> str:
    """生成任務日誌路徑（包含任務名）。"""
    safe_name = sanitize_filename(task_name)
    filename = f"{safe_name}_{task_id}.log"
    return os.path.join("logs", filename)


def resolve_task_log_path(task_id: int, task_name: str) -> str:
    """優先使用任務名生成日誌路徑，不存在時回退為按 ID 匹配。"""
    primary_path = build_task_log_path(task_id, task_name)
    if os.path.exists(primary_path):
        return primary_path
    pattern = os.path.join("logs", f"*_{task_id}.log")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    return primary_path


def get_link_unique_key(link: str) -> str:
    """擷取連結中第一個"&"之前的內容作為唯一標識依據。"""
    return link.split('&', 1)[0]


async def save_to_jsonl(data_record: dict, keyword: str):
    """相容舊呼叫名，實際將結果寫入 SQLite。"""
    try:
        return await save_result_record(data_record, keyword)
    except Exception as e:
        print(f"寫入 SQLite 結果記錄出錯: {e}")
        return False

