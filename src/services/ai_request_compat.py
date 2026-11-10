"""AI 请求兼容性辅助逻辑。"""

import copy
import re
from typing import Any, Dict, Iterable, List


RESPONSES_API_MODE = "responses"
CHAT_COMPLETIONS_API_MODE = "chat_completions"
INPUT_TEXT_TYPE = "input_text"
INPUT_IMAGE_TYPE = "input_image"
IMAGE_DETAIL_AUTO = "auto"
JSON_OUTPUT_TYPE = "json_object"
UNSUPPORTED_JSON_OUTPUT_MARKERS = (
    "not supported by this model",
    "json_object",
    "json_schema",
    "text.format",
    "response_format.type",
)
RESPONSES_API_UNSUPPORTED_MARKERS = (
    "404 page not found",
    "page not found",
    "/responses",
    "/v1/responses",
)
CHAT_COMPLETIONS_API_UNSUPPORTED_MARKERS = (
    "404 page not found",
    "page not found",
    "/chat/completions",
    "/v1/chat/completions",
)
UNSUPPORTED_TEMPERATURE_MARKERS = (
    "temperature",
    "sampling temperature",
)


def build_responses_input(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将 Chat Completions 风格的消息转换为 Responses API 输入。"""
    input_items: List[Dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        input_items.append(
            {
                "role": role,
                "content": _build_input_content(message.get("content")),
            }
        )
    return input_items


def add_json_text_format(
    request_params: Dict[str, Any],
    enabled: bool,
) -> Dict[str, Any]:
    """按需附加 Responses API 的结构化 JSON 输出参数。"""
    next_params = dict(request_params)
    if not enabled:
        return next_params

    text_config = dict(next_params.get("text") or {})
    text_config["format"] = {"type": JSON_OUTPUT_TYPE}
    next_params["text"] = text_config
    return next_params


def add_json_response_format(
    request_params: Dict[str, Any],
    enabled: bool,
) -> Dict[str, Any]:
    """按需附加 Chat Completions 的 JSON 输出参数。"""
    next_params = dict(request_params)
    if enabled:
        next_params["response_format"] = {"type": JSON_OUTPUT_TYPE}
    return next_params


def _error_details(error: Exception) -> tuple[str, str]:
    """Read both SDK and gateway error envelopes without logging their contents."""
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    body = body if isinstance(body, dict) else {}
    return (f"{error} {body.get('message', '')} {body.get('code', '')}".lower(),
            str(body.get("param") or "").lower())


def is_json_output_unsupported_error(error: Exception) -> bool:
    """Identify rejected JSON-format parameters, including Responses text.format."""
    message, param = _error_details(error)
    fields = ("response_format", "response_format.type", "text.format", "text.format.type")
    if param in fields:
        return True
    return any(marker in message for marker in fields + ("json_object", "json_schema")) and any(
        marker in message for marker in ("not supported", "unsupported", "unrecognized", "unknown parameter")
    )


def preferred_chat_token_parameter(model: str) -> str:
    """Use modern token limits for known OpenAI families, not arbitrary gateway aliases."""
    name = model.lower().rsplit("/", 1)[-1]
    if re.match(r"^(?:o[134](?:-|$)|gpt-5(?:[.-]|$))", name):
        return "max_completion_tokens"
    return "max_tokens"


def model_supports_temperature(model: str) -> bool:
    name = model.lower().rsplit("/", 1)[-1]
    # Newer families can permit sampling in selected reasoning modes. This client
    # does not select those modes, so omit sampling rather than assume support.
    return not bool(re.match(r"^(?:o[134](?:-|$)|gpt-5(?:[.-]|$))", name))


def alternate_chat_token_parameter(error: Exception, current: str) -> str | None:
    """Switch only after the currently sent token-limit field is rejected."""
    message, param = _error_details(error)
    rejected = any(word in message for word in (
        "unsupported", "not supported", "not allowed", "unrecognized", "unknown", "unexpected keyword"
    ))
    if not rejected or not (param == current or current in message):
        return None
    return "max_completion_tokens" if current == "max_tokens" else "max_tokens"


def is_responses_api_unsupported_error(error: Exception) -> bool:
    """识别 OpenAI 兼容服务未实现 Responses API 的错误。"""
    return _is_api_unsupported_error(error, RESPONSES_API_UNSUPPORTED_MARKERS)


def is_chat_completions_api_unsupported_error(error: Exception) -> bool:
    """识别 OpenAI 兼容服务未实现 Chat Completions API 的错误。"""
    return _is_api_unsupported_error(error, CHAT_COMPLETIONS_API_UNSUPPORTED_MARKERS)


def build_ai_request_params(
    api_mode: str,
    *,
    model: str,
    messages: Iterable[Dict[str, Any]],
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    enable_json_output: bool = False,
    chat_token_parameter: str | None = None,
) -> Dict[str, Any]:
    """根据 API 模式构建请求参数。"""
    request_params = {"model": model}
    if api_mode == RESPONSES_API_MODE:
        request_params["input"] = build_responses_input(messages)
        if max_output_tokens is not None:
            request_params["max_output_tokens"] = max_output_tokens
        if temperature is not None and model_supports_temperature(model):
            request_params["temperature"] = temperature
        return add_json_text_format(request_params, enable_json_output)

    if api_mode == CHAT_COMPLETIONS_API_MODE:
        request_params["messages"] = copy.deepcopy(list(messages))
        if max_output_tokens is not None:
            token_parameter = chat_token_parameter or preferred_chat_token_parameter(model)
            if token_parameter not in {"max_tokens", "max_completion_tokens"}:
                raise ValueError("Invalid Chat Completions token-limit parameter")
            request_params[token_parameter] = max_output_tokens
        if temperature is not None and model_supports_temperature(model):
            request_params["temperature"] = temperature
        return add_json_response_format(request_params, enable_json_output)

    raise ValueError(f"不支持的 AI API 模式: {api_mode}")


async def create_ai_response_async(
    client: Any,
    api_mode: str,
    request_params: Dict[str, Any],
) -> Any:
    """根据 API 模式发起异步请求。"""
    if api_mode == RESPONSES_API_MODE:
        return await client.responses.create(**request_params)
    if api_mode == CHAT_COMPLETIONS_API_MODE:
        return await client.chat.completions.create(**request_params)
    raise ValueError(f"不支持的 AI API 模式: {api_mode}")


def create_ai_response_sync(
    client: Any,
    api_mode: str,
    request_params: Dict[str, Any],
) -> Any:
    """根据 API 模式发起同步请求。"""
    if api_mode == RESPONSES_API_MODE:
        return client.responses.create(**request_params)
    if api_mode == CHAT_COMPLETIONS_API_MODE:
        return client.chat.completions.create(**request_params)
    raise ValueError(f"不支持的 AI API 模式: {api_mode}")


def is_temperature_unsupported_error(error: Exception) -> bool:
    """Identify rejected temperature values, including structured gateway errors."""
    message, param = _error_details(error)
    return (param == "temperature" or "temperature" in message) and any(
        marker in message for marker in (
            "not supported", "unsupported", "invalid", "unknown", "unrecognized", "参数错误"
        )
    )


def remove_temperature_param(request_params: Dict[str, Any]) -> Dict[str, Any]:
    """移除 temperature 参数，适配不支持采样温度的模型网关。"""
    next_params = dict(request_params)
    next_params.pop("temperature", None)
    return next_params


def _is_api_unsupported_error(
    error: Exception,
    markers: tuple[str, ...],
) -> bool:
    message, _param = _error_details(error)
    status_code = getattr(error, "status_code", None)
    # An endpoint in a 401/429/500 URL is not evidence that the API is missing.
    if status_code is not None and status_code not in {400, 404, 405, 422, 501}:
        return False
    if status_code in {400, 422}:
        return any(marker in message for marker in markers if marker.startswith("/")) and any(
            phrase in message for phrase in ("model is not supported", "not supported in", "only supported in")
        )
    if any(marker in message for marker in ("404 page not found", "page not found")):
        return True
    if any(marker in message for marker in markers) and (
        status_code in {404, 405, 501}
        or any(word in message for word in ("not supported", "unsupported", "not implemented", "404", "405", "501"))
    ):
        return True
    body = getattr(error, "body", None)
    response = getattr(error, "response", None)
    response_text = getattr(response, "text", None) if response is not None else None
    return status_code == 404 and str(error).strip().lower() == "error code: 404" and not body and not response_text


class AIRequestCompatibility:
    """Bounded per-request compatibility state; never oscillates between endpoints."""

    def __init__(self, model: str, enable_json_output: bool):
        self.model = model
        self.api_mode = CHAT_COMPLETIONS_API_MODE
        self.enable_json_output = enable_json_output
        self.use_temperature = model_supports_temperature(model)
        self.chat_token_parameter = preferred_chat_token_parameter(model)
        self._visited_modes = {self.api_mode}
        self._token_parameters_tried = {self.chat_token_parameter}

    def build(self, messages, *, temperature=0.1, max_output_tokens=4000):
        return build_ai_request_params(
            self.api_mode, model=self.model, messages=messages,
            temperature=temperature if self.use_temperature else None,
            max_output_tokens=max_output_tokens,
            enable_json_output=self.enable_json_output,
            chat_token_parameter=self.chat_token_parameter,
        )

    def adapt(self, error: Exception) -> bool:
        status = getattr(error, "status_code", None)
        if status is not None and status not in {400, 404, 405, 422, 501}:
            return False
        changed = False
        alternate = RESPONSES_API_MODE if self.api_mode == CHAT_COMPLETIONS_API_MODE else CHAT_COMPLETIONS_API_MODE
        unsupported = (is_chat_completions_api_unsupported_error(error)
                       if self.api_mode == CHAT_COMPLETIONS_API_MODE
                       else is_responses_api_unsupported_error(error))
        if unsupported and alternate not in self._visited_modes:
            self.api_mode = alternate
            self._visited_modes.add(alternate)
            changed = True
        if self.api_mode == CHAT_COMPLETIONS_API_MODE:
            token = alternate_chat_token_parameter(error, self.chat_token_parameter)
            if token and token not in self._token_parameters_tried:
                self.chat_token_parameter = token
                self._token_parameters_tried.add(token)
                changed = True
        if self.enable_json_output and is_json_output_unsupported_error(error):
            self.enable_json_output = False
            changed = True
        if self.use_temperature and is_temperature_unsupported_error(error):
            self.use_temperature = False
            changed = True
        return changed


def _build_input_content(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": INPUT_TEXT_TYPE, "text": content}]
    if not isinstance(content, list):
        raise ValueError(f"AI消息内容类型不受支持: {type(content).__name__}")

    return [_coerce_content_item(item) for item in content]


def _coerce_content_item(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"AI消息片段类型不受支持: {type(item).__name__}")

    item_type = item.get("type")
    if item_type in {"text", INPUT_TEXT_TYPE}:
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("文本消息片段缺少 text 字段。")
        return {"type": INPUT_TEXT_TYPE, "text": text}

    if item_type in {"image_url", INPUT_IMAGE_TYPE}:
        return _build_image_input_item(item)

    raise ValueError(f"不支持的 AI 消息片段类型: {item_type}")


def _build_image_input_item(item: Dict[str, Any]) -> Dict[str, Any]:
    raw_image = item.get("image_url")
    if isinstance(raw_image, dict):
        image_url = raw_image.get("url")
    else:
        image_url = raw_image

    if not isinstance(image_url, str) or not image_url.strip():
        raise ValueError("图片消息片段缺少有效的 image_url。")

    return {
        "type": INPUT_IMAGE_TYPE,
        "image_url": image_url,
        "detail": item.get("detail", IMAGE_DETAIL_AUTO),
    }
