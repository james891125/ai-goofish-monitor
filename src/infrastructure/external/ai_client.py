"""臺灣蝦皮商品使用的 OpenAI 相容分析用戶端。"""
import ipaddress
import os
import json
import base64
from typing import Dict, List, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI
from src.ai_message_builder import (
    build_analysis_text_prompt,
    build_user_message_content,
)
from src.infrastructure.config.settings import AISettings
from src.infrastructure.config.env_manager import env_manager
from src.services.ai_request_compat import AIRequestCompatibility, create_ai_response_async
from src.services.ai_analysis_validator import parse_validated_analysis
from src.services.remote_image_urls import safe_public_https_url

from src.services.ai_response_parser import (
    EmptyAIResponseError,
    extract_ai_response_content,
)


def _normalize_no_proxy_host(part: str) -> str:
    """Return an httpx-safe NO_PROXY host, or the original entry if unchanged."""
    candidate = part.strip()
    if candidate.startswith("[") and "]" in candidate:
        inner, _, suffix = candidate[1:].partition("]")
        unwrapped = f"{inner}{suffix}"
        host = unwrapped.split("/", 1)[0]
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return part
        candidate = unwrapped

    if "/" not in candidate:
        return candidate

    host, _, _prefix = candidate.partition("/")
    try:
        ipaddress.IPv6Address(host)
    except ValueError:
        return candidate
    return host


def _sanitize_no_proxy_env() -> None:
    """Normalize IPv6 entries in NO_PROXY / no_proxy for httpx <= 0.28.1.

    Two forms are rejected while building proxy mounts:

    - ``::1/128`` is wrapped as ``[::1/128]``, and the prefix is parsed as a port.
    - ``[::1]`` is not recognized as IPv6, so it becomes ``all://*[::1]`` and
      fails with ``Invalid port: ':1]'``.

    httpx only does exact-host comparison, so stripping the prefix length and
    unwrapping bracketed IPv6 literals is safe. IPv4 CIDR entries are kept.

    See https://github.com/encode/httpx/pull/3741
    """
    for key in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(key)
        if not value:
            continue
        parts = [h.strip() for h in value.split(",")]
        cleaned = [_normalize_no_proxy_host(part) for part in parts]
        if cleaned != parts:
            os.environ[key] = ",".join(cleaned)


class AIClient:
    """建立訊息、協商 API 參數並驗證商品分析。"""

    def __init__(self):
        self.settings: Optional[AISettings] = None
        self.client: Optional[AsyncOpenAI] = None
        self.refresh()

    def _load_settings(self) -> None:
        load_dotenv(dotenv_path=env_manager.env_file, override=True, interpolate=False)
        self.settings = AISettings()

    def refresh(self) -> None:
        self._load_settings()
        self.client = self._initialize_client()

    def _initialize_client(self) -> Optional[AsyncOpenAI]:
        """初始化 OpenAI 用戶端。"""
        if not self.settings or not self.settings.is_configured():
            print("警告：AI 設定不完整，請填寫 API Key、Base URL 與模型名稱")
            return None

        try:
            if self.settings.proxy_url:
                print("正在為 AI 請求使用已設定的代理")
                os.environ['HTTP_PROXY'] = self.settings.proxy_url
                os.environ['HTTPS_PROXY'] = self.settings.proxy_url

            _sanitize_no_proxy_env()

            return AsyncOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url
            )
        except Exception as e:
            print(f"初始化 AI 用戶端失敗：{type(e).__name__}")
            return None

    def is_available(self) -> bool:
        """檢查 AI 用戶端是否已初始化。"""
        return self.client is not None

    async def close(self) -> None:
        """關閉非同步用戶端，避免事件迴圈結束後仍保留連線。"""
        client = self.client
        self.client = None
        if client is None:
            return

        close = getattr(client, "close", None)
        if close is None:
            return
        await close()

    @staticmethod
    def encode_image(image_path: str) -> Optional[str]:
        """將已授權的本機圖片編碼為 Base64。"""
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"圖片編碼失敗：{type(e).__name__}")
            return None

    async def analyze(
        self,
        product_data: Dict,
        image_paths: List[str],
        prompt_text: str,
        *,
        remote_image_urls: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """分析標準商品資料，僅回傳通過結構與證據檢查的結果。"""
        if not self.is_available():
            print("AI 用戶端尚未設定")
            return None

        try:
            messages = self._build_messages(product_data, image_paths, prompt_text, remote_image_urls=remote_image_urls)
            response = await self._call_ai(messages)
            return parse_validated_analysis(response, product_data)
        except Exception as e:
            print(f"AI 分析失敗：{type(e).__name__}")
            return None

    def _build_messages(self, product_data: Dict, image_paths: List[str], prompt_text: str, *, remote_image_urls: Optional[List[str]] = None) -> List[Dict]:
        """建立文字或多模態訊息，不下載遠端圖片。"""
        product_json = json.dumps(product_data, ensure_ascii=False, indent=2)
        image_data_urls: List[str] = [
            validated for url in (remote_image_urls or [])[:8]
            if (validated := safe_public_https_url(url)) is not None
        ]
        for path in image_paths:
            base64_img = self.encode_image(path)
            if base64_img:
                image_data_urls.append(f"data:image/jpeg;base64,{base64_img}")

        text_prompt = build_analysis_text_prompt(
            product_json,
            prompt_text,
            include_images=bool(image_data_urls),
        )
        user_content = build_user_message_content(text_prompt, image_data_urls)
        return [{"role": "user", "content": user_content}]

    async def _call_ai(
        self,
        messages: List[Dict],
        *,
        temperature: float = 0.1,
        max_output_tokens: int = 4000,
        enable_json_output: Optional[bool] = None,
    ) -> str:
        """Call an OpenAI-compatible endpoint with bounded capability fallbacks."""
        state = AIRequestCompatibility(
            self.settings.model_name,
            self.settings.enable_response_format if enable_json_output is None else enable_json_output,
        )
        empty_responses = 0
        # Four content attempts plus token, endpoint, JSON and temperature adaptation.
        for _attempt in range(8):
            request_params = state.build(
                messages, temperature=temperature, max_output_tokens=max_output_tokens,
            )
            try:
                response = await create_ai_response_async(self.client, state.api_mode, request_params)
                return extract_ai_response_content(response)
            except EmptyAIResponseError:
                empty_responses += 1
                if empty_responses >= 4:
                    raise
            except Exception as exc:
                if not state.adapt(exc):
                    raise
        raise RuntimeError("AI 呼叫在相容性重試後仍未回傳結果")
