"""
通知客戶端工廠
"""
from src.infrastructure.config.settings import NotificationSettings

from .webhook_client import WebhookClient


def build_notification_clients(settings: NotificationSettings):
    return [
        WebhookClient(
            settings.webhook_url,
            webhook_method=settings.webhook_method,
            webhook_headers=settings.webhook_headers,
            webhook_content_type=settings.webhook_content_type,
            webhook_query_parameters=settings.webhook_query_parameters,
            webhook_body=settings.webhook_body,
        ),
    ]
