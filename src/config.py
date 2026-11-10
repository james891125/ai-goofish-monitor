import os
import sys

from dotenv import load_dotenv
from openai import AsyncOpenAI

from src.infrastructure.external.ai_client import _sanitize_no_proxy_env

# --- AI & Notification Configuration ---
load_dotenv()

# --- File Paths & Directories ---
STATE_FILE = "shopee_state.json"
IMAGE_SAVE_DIR = "images"
CONFIG_FILE = "config.json"
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

# 任務隔離的臨時圖片目錄字首
TASK_IMAGE_DIR_PREFIX = "task_images_"

# --- Environment Variables ---
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")
PROXY_URL = os.getenv("PROXY_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_METHOD = os.getenv("WEBHOOK_METHOD", "POST").upper()
WEBHOOK_HEADERS = os.getenv("WEBHOOK_HEADERS")
WEBHOOK_CONTENT_TYPE = os.getenv("WEBHOOK_CONTENT_TYPE", "JSON").upper()
WEBHOOK_QUERY_PARAMETERS = os.getenv("WEBHOOK_QUERY_PARAMETERS")
WEBHOOK_BODY = os.getenv("WEBHOOK_BODY")
RUN_HEADLESS = os.getenv("RUN_HEADLESS", "true").lower() != "false"
LOGIN_IS_EDGE = os.getenv("LOGIN_IS_EDGE", "false").lower() == "true"
RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"
AI_DEBUG_MODE = os.getenv("AI_DEBUG_MODE", "false").lower() == "true"
SKIP_AI_ANALYSIS = os.getenv("SKIP_AI_ANALYSIS", "false").lower() == "true"
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "false").lower() == "true"
ENABLE_RESPONSE_FORMAT = os.getenv("ENABLE_RESPONSE_FORMAT", "true").lower() == "true"

# --- Headers ---
IMAGE_DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0',
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# --- Client Initialization ---
# 檢查配置是否齊全
if not all([BASE_URL, MODEL_NAME]):
    print("警告：未在 .env 檔案中完整設定 OPENAI_BASE_URL 和 OPENAI_MODEL_NAME。AI相關功能可能無法使用。")
    client = None
else:
    try:
        # 舊客戶端和 AIClient 必須在建立前共用同一套 NO_PROXY 清理。
        _sanitize_no_proxy_env()
        if PROXY_URL:
            print(f"正在為AI請求使用HTTP/S代理: {PROXY_URL}")
            # httpx 會自動從環境變數中讀取代理設定
            os.environ['HTTP_PROXY'] = PROXY_URL
            os.environ['HTTPS_PROXY'] = PROXY_URL

        # openai 客戶端內部的 httpx 會自動從環境變數中獲取代理配置
        client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
    except Exception as e:
        print(f"初始化 OpenAI 客戶端時出錯: {e}")
        client = None

# 檢查AI客戶端是否成功初始化
if not client:
    # 在 prompt_generator.py 中，如果 client 為 None，會直接報錯退出
    # 在 spider_v2.py 中，AI分析會跳過
    # 為了保持一致性，這裡只列印警告，具體邏輯由呼叫方處理
    pass

# 檢查關鍵配置
if not all([BASE_URL, MODEL_NAME]) and 'prompt_generator.py' in sys.argv[0]:
    sys.exit("錯誤：請確保在 .env 檔案中完整設定了 OPENAI_BASE_URL 和 OPENAI_MODEL_NAME。(OPENAI_API_KEY 對於某些服務是可選的)")

def get_ai_request_params(**kwargs):
    """
    構建AI請求參數，根據ENABLE_THINKING和ENABLE_RESPONSE_FORMAT環境變數決定是否新增相應參數
    """
    if ENABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}
    
    # 如果禁用結構化輸出，則移除 text.format 配置
    if not ENABLE_RESPONSE_FORMAT and "text" in kwargs:
        text_config = kwargs.get("text")
        if isinstance(text_config, dict):
            text_config = dict(text_config)
            text_config.pop("format", None)
            if text_config:
                kwargs["text"] = text_config
            else:
                del kwargs["text"]
    
    return kwargs
