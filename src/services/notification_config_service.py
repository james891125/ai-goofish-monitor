"""
通知配置讀寫與校驗服務
"""
import json
from urllib.parse import urlparse

from src.infrastructure.config.env_manager import env_manager
from src.infrastructure.config.settings import NotificationSettings


NOTIFICATION_FIELD_MAP = {
    "WEBHOOK_URL": "webhook_url",
    "WEBHOOK_METHOD": "webhook_method",
    "WEBHOOK_HEADERS": "webhook_headers",
    "WEBHOOK_CONTENT_TYPE": "webhook_content_type",
    "WEBHOOK_QUERY_PARAMETERS": "webhook_query_parameters",
    "WEBHOOK_BODY": "webhook_body",
}

CHANNEL_NOTIFICATION_FIELDS = {
    "webhook": {
        "WEBHOOK_URL",
        "WEBHOOK_METHOD",
        "WEBHOOK_HEADERS",
        "WEBHOOK_CONTENT_TYPE",
        "WEBHOOK_QUERY_PARAMETERS",
        "WEBHOOK_BODY",
    },
}

SECRET_NOTIFICATION_FIELDS = {
    "WEBHOOK_URL",
    "WEBHOOK_HEADERS",
}

JSON_NOTIFICATION_FIELDS = {
    "WEBHOOK_HEADERS": True,
    "WEBHOOK_QUERY_PARAMETERS": True,
    "WEBHOOK_BODY": False,
}

URL_FIELDS = {
    "WEBHOOK_URL",
}

ALLOWED_WEBHOOK_METHODS = {"GET", "POST"}
ALLOWED_WEBHOOK_CONTENT_TYPES = {"JSON", "FORM"}


class NotificationSettingsValidationError(ValueError):
    """通知配置校驗錯誤"""


def model_dump(model, *, exclude_unset: bool = False) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def build_notification_settings_response(
    settings: NotificationSettings | None = None,
) -> dict:
    notification_settings = settings or load_notification_settings()
    response = {
        "WEBHOOK_URL": "",
        "WEBHOOK_METHOD": notification_settings.webhook_method,
        "WEBHOOK_HEADERS": "",
        "WEBHOOK_CONTENT_TYPE": notification_settings.webhook_content_type,
        "WEBHOOK_QUERY_PARAMETERS": notification_settings.webhook_query_parameters or "",
        "WEBHOOK_BODY": notification_settings.webhook_body or "",
    }
    for field in SECRET_NOTIFICATION_FIELDS:
        attr_name = NOTIFICATION_FIELD_MAP[field]
        response[f"{field}_SET"] = bool(getattr(notification_settings, attr_name))
    response["CONFIGURED_CHANNELS"] = build_configured_channels(notification_settings)
    return response


def build_notification_status_flags(
    settings: NotificationSettings | None = None,
) -> dict:
    notification_settings = settings or load_notification_settings()
    return {
        "webhook_url_set": bool(notification_settings.webhook_url),
        "webhook_headers_set": bool(notification_settings.webhook_headers),
    }


def build_configured_channels(
    settings: NotificationSettings | None = None,
) -> list[str]:
    notification_settings = settings or load_notification_settings()
    channels = []
    if notification_settings.webhook_url:
        channels.append("webhook")
    return channels


def prepare_notification_settings_update(
    patch_payload: dict,
    existing_settings: NotificationSettings | None = None,
) -> tuple[dict[str, str], list[str], NotificationSettings]:
    current_settings = existing_settings or load_notification_settings()
    merged_values = _notification_settings_to_values(current_settings)

    for env_name, raw_value in patch_payload.items():
        attr_name = NOTIFICATION_FIELD_MAP.get(env_name)
        if attr_name is None:
            continue
        merged_values[attr_name] = _normalize_patch_value(env_name, raw_value)

    normalized_values = _normalize_notification_values(merged_values)
    candidate_settings = _build_notification_settings_model(normalized_values)
    _validate_notification_settings(candidate_settings)

    updates = {}
    deletions = []
    for env_name, raw_value in patch_payload.items():
        attr_name = NOTIFICATION_FIELD_MAP.get(env_name)
        if attr_name is None:
            continue
        value = normalized_values[attr_name]
        if isinstance(value, bool):
            updates[env_name] = "true" if value else "false"
            continue
        if value is None:
            deletions.append(env_name)
            continue
        updates[env_name] = value
    return updates, deletions, candidate_settings


def prepare_notification_test_settings(
    patch_payload: dict,
    existing_settings: NotificationSettings | None = None,
    *,
    channel: str | None = None,
) -> NotificationSettings:
    if channel is None:
        _, _, merged_settings = prepare_notification_settings_update(
            patch_payload,
            existing_settings,
        )
        return merged_settings

    if channel not in CHANNEL_NOTIFICATION_FIELDS:
        raise NotificationSettingsValidationError(f"不支援的通知渠道: {channel}")

    current_settings = existing_settings or load_notification_settings()
    included_env_fields = set(CHANNEL_NOTIFICATION_FIELDS[channel])
    merged_values = _build_channel_test_values(current_settings, included_env_fields)

    for env_name, raw_value in patch_payload.items():
        if env_name not in included_env_fields:
            continue
        attr_name = NOTIFICATION_FIELD_MAP[env_name]
        merged_values[attr_name] = _normalize_patch_value(env_name, raw_value)

    normalized_values = _normalize_notification_values(merged_values)
    candidate_settings = _build_notification_settings_model(normalized_values)
    _validate_notification_settings(candidate_settings)
    return candidate_settings


def _notification_settings_to_values(settings: NotificationSettings) -> dict:
    return {
        attr_name: getattr(settings, attr_name)
        for attr_name in NOTIFICATION_FIELD_MAP.values()
    }


def _build_channel_test_values(
    settings: NotificationSettings,
    included_env_fields: set[str],
) -> dict:
    values = {
        attr_name: None
        for attr_name in NOTIFICATION_FIELD_MAP.values()
    }
    values["webhook_method"] = "POST"
    values["webhook_content_type"] = "JSON"

    for env_name in included_env_fields:
        attr_name = NOTIFICATION_FIELD_MAP[env_name]
        values[attr_name] = getattr(settings, attr_name)

    return values


def load_notification_settings() -> NotificationSettings:
    return _build_notification_settings_model(
        {
            "webhook_url": _normalize_existing_text(env_manager.get_value("WEBHOOK_URL")),
            "webhook_method": _normalize_existing_text(env_manager.get_value("WEBHOOK_METHOD")) or "POST",
            "webhook_headers": _normalize_existing_text(env_manager.get_value("WEBHOOK_HEADERS")),
            "webhook_content_type": _normalize_existing_text(env_manager.get_value("WEBHOOK_CONTENT_TYPE")) or "JSON",
            "webhook_query_parameters": _normalize_existing_text(env_manager.get_value("WEBHOOK_QUERY_PARAMETERS")),
            "webhook_body": _normalize_existing_text(env_manager.get_value("WEBHOOK_BODY")),
        }
    )


def _build_notification_settings_model(values: dict) -> NotificationSettings:
    if hasattr(NotificationSettings, "model_construct"):
        return NotificationSettings.model_construct(**values)
    return NotificationSettings.construct(**values)


def _normalize_patch_value(env_name: str, value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_existing_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def _normalize_notification_values(values: dict) -> dict:
    normalized = dict(values)
    normalized["webhook_method"] = (
        (normalized.get("webhook_method") or "POST").strip().upper()
    )
    normalized["webhook_content_type"] = (
        (normalized.get("webhook_content_type") or "JSON").strip().upper()
    )

    for env_name, expect_dict in JSON_NOTIFICATION_FIELDS.items():
        attr_name = NOTIFICATION_FIELD_MAP[env_name]
        raw_value = normalized.get(attr_name)
        if raw_value is None:
            continue
        parsed = _parse_json_field(env_name, raw_value, expect_dict=expect_dict)
        normalized[attr_name] = json.dumps(
            parsed,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return normalized


def _validate_notification_settings(settings: NotificationSettings) -> None:
    for field_name in URL_FIELDS:
        value = getattr(settings, NOTIFICATION_FIELD_MAP[field_name])
        if value is not None:
            _validate_http_url(field_name, value)

    if settings.webhook_method not in ALLOWED_WEBHOOK_METHODS:
        allowed = ", ".join(sorted(ALLOWED_WEBHOOK_METHODS))
        raise NotificationSettingsValidationError(
            f"WEBHOOK_METHOD 僅支援: {allowed}"
        )
    if settings.webhook_content_type not in ALLOWED_WEBHOOK_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_WEBHOOK_CONTENT_TYPES))
        raise NotificationSettingsValidationError(
            f"WEBHOOK_CONTENT_TYPE 僅支援: {allowed}"
        )

    has_webhook_extras = any(
        [
            settings.webhook_headers,
            settings.webhook_query_parameters,
            settings.webhook_body,
        ]
    )
    if has_webhook_extras and not settings.webhook_url:
        raise NotificationSettingsValidationError(
            "配置 Webhook 高階參數前必須先填寫 WEBHOOK_URL"
        )

    if settings.webhook_content_type == "FORM" and settings.webhook_body:
        parsed_body = json.loads(settings.webhook_body)
        if not isinstance(parsed_body, dict):
            raise NotificationSettingsValidationError(
                "WEBHOOK_BODY 在 FORM 模式下必須是 JSON 物件"
            )


def _validate_http_url(field_name: str, value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NotificationSettingsValidationError(
            f"{field_name} 必須是合法的 HTTP/HTTPS URL"
        )



def _parse_json_field(
    field_name: str,
    raw_value: str,
    expect_dict: bool,
):
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise NotificationSettingsValidationError(
            f"{field_name} 不是合法 JSON: {exc.msg}"
        ) from exc
    if expect_dict and not isinstance(parsed, dict):
        raise NotificationSettingsValidationError(
            f"{field_name} 必須是 JSON 物件"
        )
    return parsed
