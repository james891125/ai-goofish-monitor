"""
AI 客戶端封裝
提供統一的 AI 呼叫介面
"""
import ipaddress
import os
import json
import base64
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI
from src.ai_message_builder import (
    build_analysis_text_prompt,
    build_user_message_content,
)
from src.infrastructure.config.settings import AISettings
from src.infrastructure.config.env_manager import env_manager
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
from src.services.ai_response_parser import (
    EmptyAIResponseError,
    extract_ai_response_content,
    parse_ai_response_json,
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
    """AI 客戶端封裝"""

    def __init__(self):
        self.settings: Optional[AISettings] = None
        self.client: Optional[AsyncOpenAI] = None
        self.refresh()

    def _load_settings(self) -> None:
        load_dotenv(dotenv_path=env_manager.env_file, override=True)
        self.settings = AISettings()

    def refresh(self) -> None:
        self._load_settings()
        self.client = self._initialize_client()

    def _initialize_client(self) -> Optional[AsyncOpenAI]:
        """初始化 OpenAI 客戶端"""
        if not self.settings or not self.settings.is_configured():
            print("警告：AI 配置不完整，AI 功能將不可用")
            return None

        try:
            if self.settings.proxy_url:
                print(f"正在為 AI 請求使用代理: {self.settings.proxy_url}")
                os.environ['HTTP_PROXY'] = self.settings.proxy_url
                os.environ['HTTPS_PROXY'] = self.settings.proxy_url

            _sanitize_no_proxy_env()

            return AsyncOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url
            )
        except Exception as e:
            print(f"初始化 AI 客戶端失敗: {e}")
            return None

    def is_available(self) -> bool:
        """檢查 AI 客戶端是否可用"""
        return self.client is not None

    async def close(self) -> None:
        """關閉底層非同步客戶端，避免事件迴圈結束後再觸發清理。"""
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
        """將圖片編碼為 Base64"""
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"編碼圖片失敗: {e}")
            return None

    async def analyze(
        self,
        product_data: Dict,
        image_paths: List[str],
        prompt_text: str
    ) -> Optional[Dict]:
        """
        分析商品資料

        Args:
            product_data: 商品資料
            image_paths: 圖片路徑列表
            prompt_text: 分析提示詞

        Returns:
            分析結果
        """
        if not self.is_available():
            print("AI 客戶端不可用")
            return None

        try:
            messages = self._build_messages(product_data, image_paths, prompt_text)
            response = await self._call_ai(messages)
            return self._parse_response(response)
        except Exception as e:
            print(f"AI 分析失敗: {e}")
            return None

    def _build_messages(self, product_data: Dict, image_paths: List[str], prompt_text: str) -> List[Dict]:
        """構建 AI 訊息"""
        product_json = json.dumps(product_data, ensure_ascii=False, indent=2)
        image_data_urls: List[str] = []
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
        """呼叫 AI API"""
        api_mode = CHAT_COMPLETIONS_API_MODE
        use_response_format = (
            self.settings.enable_response_format
            if enable_json_output is None
            else enable_json_output
        )
        use_temperature = True
        max_attempts = 4

        for attempt in range(max_attempts):
            request_params = build_ai_request_params(
                api_mode,
                model=self.settings.model_name,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                enable_json_output=use_response_format,
            )
            if not use_temperature:
                request_params = remove_temperature_param(request_params)

            if self.settings.enable_thinking:
                request_params["extra_body"] = {"enable_thinking": False}

            try:
                response = await create_ai_response_async(
                    self.client,
                    api_mode,
                    request_params,
                )
                return extract_ai_response_content(response)
            except EmptyAIResponseError as exc:
                if attempt < max_attempts - 1:
                    print(
                        f"AI響應為空，正在自動重試 ({attempt + 2}/{max_attempts})"
                    )
                    continue
                raise exc
            except Exception as exc:
                changed = False
                if (
                    api_mode == CHAT_COMPLETIONS_API_MODE
                    and is_chat_completions_api_unsupported_error(exc)
                ):
                    api_mode = RESPONSES_API_MODE
                    changed = True
                    print("目前服務未實現 Chat Completions API，正在自動回退到 Responses API")
                elif (
                    api_mode == RESPONSES_API_MODE
                    and is_responses_api_unsupported_error(exc)
                ):
                    api_mode = CHAT_COMPLETIONS_API_MODE
                    changed = True
                    print("目前服務未實現 Responses API，正在自動回退到 Chat Completions API")
                if use_response_format and is_json_output_unsupported_error(exc):
                    use_response_format = False
                    changed = True
                    print("目前模型不支援結構化 JSON 輸出，正在自動重試並移除該參數")
                if use_temperature and is_temperature_unsupported_error(exc):
                    use_temperature = False
                    changed = True
                    print("目前模型不支援 temperature 參數，正在自動重試並移除該參數")
                if changed and attempt < max_attempts - 1:
                    continue
                raise

        raise RuntimeError("AI 呼叫在相容性重試後仍未返回結果")

    def _parse_response(self, response_text: str) -> Optional[Dict]:
        """解析 AI 響應"""
        try:
            return parse_ai_response_json(response_text)
        except json.JSONDecodeError:
            print(f"無法解析 AI 響應: {response_text[:100]}")
            return None
