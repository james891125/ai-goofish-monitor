import asyncio
import base64
import json
import os
import re
import sys
import shutil
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import requests

# 設定標準輸出編碼為UTF-8，解決Windows控制檯編碼問題
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

from src.config import (
    AI_DEBUG_MODE,
    IMAGE_DOWNLOAD_HEADERS,
    IMAGE_SAVE_DIR,
    TASK_IMAGE_DIR_PREFIX,
    MODEL_NAME,
    ENABLE_RESPONSE_FORMAT,
    client,
)
from src.ai_message_builder import (
    build_analysis_text_prompt,
    build_user_message_content,
)
from src.services.ai_response_parser import (
    EmptyAIResponseError,
    extract_ai_response_content,
    parse_ai_response_json,
)
from src.services.ai_request_compat import (
    CHAT_COMPLETIONS_API_MODE,
    RESPONSES_API_MODE,
    build_ai_request_params,
    create_ai_response_async,
    is_chat_completions_api_unsupported_error,
    is_json_output_unsupported_error,
    is_responses_api_unsupported_error,
    is_temperature_unsupported_error,
    remove_temperature_param,
)
from src.services.notification_service import build_notification_service
from src.utils import retry_on_failure


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


DEFAULT_IMAGE_DOWNLOAD_CONCURRENCY = max(
    1,
    _positive_int(os.getenv("IMAGE_DOWNLOAD_CONCURRENCY", "3"), 3),
)


def safe_print(text):
    """安全的列印函式，處理編碼錯誤"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 如果遇到編碼錯誤，嘗試用ASCII編碼並忽略無法編碼的字元
        try:
            print(text.encode('ascii', errors='ignore').decode('ascii'))
        except:
            # 如果還是失敗，列印一個簡化的訊息
            print("[輸出包含無法顯示的字元]")


def _build_debug_request_summary(api_mode: str, request_params: dict) -> dict:
    summary = {
        "api_mode": api_mode,
        "model": request_params.get("model"),
    }
    if "temperature" in request_params:
        summary["temperature"] = request_params["temperature"]
    if "max_output_tokens" in request_params:
        summary["max_output_tokens"] = request_params["max_output_tokens"]
    if "max_completion_tokens" in request_params:
        summary["max_completion_tokens"] = request_params["max_completion_tokens"]
    if "text" in request_params:
        summary["text"] = request_params["text"]
    if "response_format" in request_params:
        summary["response_format"] = request_params["response_format"]
    if "input" in request_params:
        summary["input_content_types"] = [
            [item.get("type") for item in message.get("content", [])]
            for message in request_params["input"]
        ]
    if "messages" in request_params:
        summary["message_content_types"] = [
            _extract_message_content_types(message)
            for message in request_params["messages"]
        ]
    return summary


def _extract_message_content_types(message: dict) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return ["text"]
    if not isinstance(content, list):
        return [type(content).__name__]
    return [str(item.get("type")) for item in content if isinstance(item, dict)]


@retry_on_failure(retries=2, delay=3)
async def _download_single_image(url, save_path):
    """一個帶重試的內部函式，用於非同步下載單個圖片。"""
    loop = asyncio.get_running_loop()
    # 使用 run_in_executor 執行同步的 requests 程式碼，避免阻塞事件迴圈
    response = await loop.run_in_executor(
        None,
        lambda: requests.get(url, headers=IMAGE_DOWNLOAD_HEADERS, timeout=20, stream=True)
    )
    response.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


def _build_image_save_path(
    product_id: str,
    index: int,
    url: str,
    task_image_dir: str,
) -> str:
    clean_url = url.split('.heic')[0] if '.heic' in url else url
    file_name_base = os.path.basename(clean_url).split('?')[0]
    file_name = f"product_{product_id}_{index}_{file_name_base}"
    file_name = re.sub(r'[\\/*?:"<>|]', "", file_name)
    if not os.path.splitext(file_name)[1]:
        file_name += ".jpg"
    return os.path.join(task_image_dir, file_name)


async def download_all_images(product_id, image_urls, task_name="default", concurrency=None):
    """非同步下載一個商品的所有圖片。如果圖片已存在則跳過。支援任務隔離。"""
    if not image_urls:
        return []

    # 為每個任務建立獨立的圖片目錄
    task_image_dir = os.path.join(IMAGE_SAVE_DIR, f"{TASK_IMAGE_DIR_PREFIX}{task_name}")
    os.makedirs(task_image_dir, exist_ok=True)

    urls = [url.strip() for url in image_urls if url.strip().startswith('http')]
    if not urls:
        return []

    max_concurrency = _positive_int(concurrency, DEFAULT_IMAGE_DOWNLOAD_CONCURRENCY)
    semaphore = asyncio.Semaphore(max_concurrency)
    total_images = len(urls)

    async def _download_one(index: int, url: str):
        save_path = _build_image_save_path(product_id, index, url, task_image_dir)
        if os.path.exists(save_path):
            safe_print(
                f"   [圖片] 圖片 {index}/{total_images} 已存在，跳過下載: {os.path.basename(save_path)}"
            )
            return save_path
        async with semaphore:
            safe_print(f"   [圖片] 正在下載圖片 {index}/{total_images}: {url}")
            if await _download_single_image(url, save_path):
                safe_print(
                    f"   [圖片] 圖片 {index}/{total_images} 已成功下載到: {os.path.basename(save_path)}"
                )
                return save_path
        return None

    tasks = [
        asyncio.create_task(_download_one(index, url))
        for index, url in enumerate(urls, start=1)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    saved_paths = []
    for url, result in zip(urls, results):
        try:
            if isinstance(result, Exception):
                raise result
            if result:
                saved_paths.append(result)
        except Exception as e:
            safe_print(f"   [圖片] 處理圖片 {url} 時發生錯誤，已跳過此圖: {e}")

    return saved_paths


def cleanup_task_images(task_name):
    """清理指定任務的圖片目錄"""
    task_image_dir = os.path.join(IMAGE_SAVE_DIR, f"{TASK_IMAGE_DIR_PREFIX}{task_name}")
    if os.path.exists(task_image_dir):
        try:
            shutil.rmtree(task_image_dir)
            safe_print(f"   [清理] 已刪除任務 '{task_name}' 的臨時圖片目錄: {task_image_dir}")
        except Exception as e:
            safe_print(f"   [清理] 刪除任務 '{task_name}' 的臨時圖片目錄時出錯: {e}")
    else:
        safe_print(f"   [清理] 任務 '{task_name}' 的臨時圖片目錄不存在: {task_image_dir}")


def cleanup_ai_logs(logs_dir: str, keep_days: int = 1) -> None:
    try:
        cutoff = datetime.now() - timedelta(days=keep_days)
        for filename in os.listdir(logs_dir):
            if not filename.endswith(".log"):
                continue
            try:
                timestamp = datetime.strptime(filename[:15], "%Y%m%d_%H%M%S")
            except ValueError:
                continue
            if timestamp < cutoff:
                os.remove(os.path.join(logs_dir, filename))
    except Exception as e:
        safe_print(f"   [日誌] 清理AI日誌時出錯: {e}")


def encode_image_to_base64(image_path):
    """將本地圖片檔案編碼為 Base64 字串。"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        safe_print(f"編碼圖片時出錯: {e}")
        return None


def validate_ai_response_format(parsed_response):
    """驗證AI響應的格式是否符合預期結構"""
    required_fields = [
        "prompt_version",
        "is_recommended",
        "reason",
        "risk_tags",
        "criteria_analysis"
    ]

    # 檢查頂層欄位
    for field in required_fields:
        if field not in parsed_response:
            safe_print(f"   [AI分析] 警告：響應缺少必需欄位 '{field}'")
            return False

    # 檢查criteria_analysis是否為字典且不為空
    criteria_analysis = parsed_response.get("criteria_analysis", {})
    if not isinstance(criteria_analysis, dict) or not criteria_analysis:
        safe_print("   [AI分析] 警告：criteria_analysis必須是非空字典")
        return False

    # 檢查seller_type欄位（所有商品都需要）
    if "seller_type" not in criteria_analysis:
        safe_print("   [AI分析] 警告：criteria_analysis缺少必需欄位 'seller_type'")
        return False

    # 檢查資料型別
    if not isinstance(parsed_response.get("is_recommended"), bool):
        safe_print("   [AI分析] 警告：is_recommended欄位不是布林型別")
        return False

    if not isinstance(parsed_response.get("risk_tags"), list):
        safe_print("   [AI分析] 警告：risk_tags欄位不是列表型別")
        return False

    return True


@retry_on_failure(retries=3, delay=5)
async def send_notification(product_data, reason):
    """相容舊呼叫名，內部統一走 NotificationService。"""
    service = build_notification_service()
    if not service.clients:
        safe_print(
            "警告：未在 .env 檔案中配置任何通知服務，跳過通知。"
        )
        return {}

    results = await service.send_notification(product_data, reason)
    for channel, result in results.items():
        if result["success"]:
            safe_print(f"   -> {channel} 通知傳送成功。")
            continue
        safe_print(f"   -> {channel} 通知傳送失敗: {result['message']}")
    return results


async def get_ai_analysis(product_data, image_paths=None, prompt_text=""):
    """將完整的商品JSON資料和所有圖片傳送給 AI 進行分析（非同步）。"""
    if not client:
        safe_print("   [AI分析] 錯誤：AI客戶端未初始化，跳過分析。")
        return None

    item_info = product_data.get('商品資訊', {})
    product_id = item_info.get('商品ID', 'N/A')

    safe_print(f"\n   [AI分析] 開始分析商品 #{product_id} (含 {len(image_paths or [])} 張圖片)...")
    safe_print(f"   [AI分析] 標題: {item_info.get('商品標題', '無')}")

    if not prompt_text:
        safe_print("   [AI分析] 錯誤：未提供AI分析所需的prompt文字。")
        return None

    product_details_json = json.dumps(product_data, ensure_ascii=False, indent=2)
    system_prompt = prompt_text

    if AI_DEBUG_MODE:
        safe_print("\n--- [AI DEBUG] ---")
        safe_print("--- PRODUCT DATA (JSON) ---")
        safe_print(product_details_json)
        safe_print("--- PROMPT TEXT (完整內容) ---")
        safe_print(prompt_text)
        safe_print("-------------------\n")

    image_data_urls = []
    if image_paths:
        for path in image_paths:
            base64_image = encode_image_to_base64(path)
            if base64_image:
                image_data_urls.append(f"data:image/jpeg;base64,{base64_image}")

    combined_text_prompt = build_analysis_text_prompt(
        product_details_json,
        system_prompt,
        include_images=bool(image_data_urls),
    )
    user_content = build_user_message_content(combined_text_prompt, image_data_urls)
    messages = [{"role": "user", "content": user_content}]

    # 儲存最終傳輸內容到日誌檔案
    try:
        # 建立logs資料夾
        logs_dir = os.path.join("logs", "ai")
        os.makedirs(logs_dir, exist_ok=True)
        cleanup_ai_logs(logs_dir, keep_days=1)

        # 生成日誌檔名（目前時間）
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{current_time}.log"
        log_filepath = os.path.join(logs_dir, log_filename)

        task_name = product_data.get("任務名稱") or product_data.get("任務名") or "unknown"
        log_payload = {
            "timestamp": current_time,
            "task_name": task_name,
            "product_id": product_id,
            "title": item_info.get("商品標題", "無"),
            "image_count": len(image_data_urls),
        }
        log_content = json.dumps(log_payload, ensure_ascii=False)

        # 寫入日誌檔案
        with open(log_filepath, 'w', encoding='utf-8') as f:
            f.write(log_content)

        safe_print(f"   [日誌] AI分析請求已儲存到: {log_filepath}")

    except Exception as e:
        safe_print(f"   [日誌] 儲存AI分析日誌時出錯: {e}")

    # 增強的AI呼叫，包含更嚴格的結構化輸出控制和重試機制
    max_retries = 4
    api_mode = CHAT_COMPLETIONS_API_MODE
    use_response_format = ENABLE_RESPONSE_FORMAT
    use_temperature = True
    for attempt in range(max_retries):
        try:
            # 根據重試次數調整參數
            current_temperature = 0.1 if attempt == 0 else 0.05  # 重試時使用更低的溫度

            from src.config import get_ai_request_params

            request_params = build_ai_request_params(
                api_mode,
                model=MODEL_NAME,
                messages=messages,
                temperature=current_temperature,
                max_output_tokens=4000,
                enable_json_output=use_response_format,
            )
            if not use_temperature:
                request_params = remove_temperature_param(request_params)

            request_params = get_ai_request_params(**request_params)

            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] 第{attempt + 1}次嘗試 REQUEST ---")
                safe_print(
                    json.dumps(
                        _build_debug_request_summary(api_mode, request_params),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                safe_print("-----------------------------------\n")

            response = await create_ai_response_async(
                client,
                api_mode,
                request_params,
            )
            ai_response_content = extract_ai_response_content(response)

            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] 第{attempt + 1}次嘗試 ---")
                safe_print("--- RAW AI RESPONSE ---")
                safe_print(ai_response_content)
                safe_print("---------------------\n")

            try:
                parsed_response = parse_ai_response_json(ai_response_content)

                # 驗證響應格式
                if validate_ai_response_format(parsed_response):
                    safe_print(f"   [AI分析] 第{attempt + 1}次嘗試成功，響應格式驗證透過")
                    return parsed_response
                safe_print(f"   [AI分析] 第{attempt + 1}次嘗試格式驗證失敗")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 準備第{attempt + 2}次重試...")
                    continue
                raise ValueError("AI響應格式缺少必需欄位或欄位型別不正確。")
            except json.JSONDecodeError as e:
                safe_print(f"   [AI分析] 第{attempt + 1}次嘗試JSON解析失敗: {e}")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 準備第{attempt + 2}次重試...")
                    continue
                raise e
            except EmptyAIResponseError as e:
                safe_print(f"   [AI分析] 第{attempt + 1}次嘗試返回空響應: {e}")
                if attempt < max_retries - 1:
                    safe_print(f"   [AI分析] 準備第{attempt + 2}次重試...")
                    continue
                raise e

        except Exception as e:
            if (
                api_mode == CHAT_COMPLETIONS_API_MODE
                and is_chat_completions_api_unsupported_error(e)
            ):
                api_mode = RESPONSES_API_MODE
                safe_print(
                    "   [AI分析] 目前服務未實現 Chat Completions API，後續重試將自動回退到 Responses API。"
                )
            elif api_mode == RESPONSES_API_MODE and is_responses_api_unsupported_error(e):
                api_mode = CHAT_COMPLETIONS_API_MODE
                safe_print(
                    "   [AI分析] 目前服務未實現 Responses API，後續重試將自動回退到 Chat Completions API。"
                )
            if use_response_format and is_json_output_unsupported_error(e):
                use_response_format = False
                safe_print(
                    "   [AI分析] 目前模型不支援結構化 JSON 輸出，後續重試將自動禁用該參數。"
                )
            if use_temperature and is_temperature_unsupported_error(e):
                use_temperature = False
                safe_print(
                    "   [AI分析] 目前模型不支援 temperature 參數，後續重試將自動禁用該參數。"
                )
            if AI_DEBUG_MODE:
                safe_print(f"\n--- [AI DEBUG] 第{attempt + 1}次嘗試 EXCEPTION ---")
                safe_print(repr(e))
                safe_print(traceback.format_exc())
                safe_print("-------------------------------------\n")
            safe_print(f"   [AI分析] 第{attempt + 1}次嘗試AI呼叫失敗: {e}")
            if attempt < max_retries - 1:
                safe_print(f"   [AI分析] 準備第{attempt + 2}次重試...")
                continue
            else:
                raise e
