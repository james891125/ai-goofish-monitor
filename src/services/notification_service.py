"""
通知服務
統一管理所有通知渠道
"""
import asyncio
from typing import Dict, List

from src.infrastructure.external.notification_clients.base import NotificationClient
from src.infrastructure.external.notification_clients.factory import build_notification_clients
from src.services.notification_config_service import load_notification_settings
from src.infrastructure.config.settings import NotificationSettings


class NotificationService:
    """通知服務"""

    def __init__(self, clients: List[NotificationClient]):
        self.clients = [client for client in clients if client.is_enabled()]

    async def send_notification(
        self,
        product_data: Dict,
        reason: str,
    ) -> Dict[str, Dict[str, str | bool]]:
        """
        傳送通知到所有啟用的渠道

        Returns:
            各渠道傳送結果，包含成功狀態和訊息
        """
        if not self.clients:
            return {}

        tasks = [
            self._send_with_result(client, product_data, reason)
            for client in self.clients
        ]
        results = await asyncio.gather(*tasks)
        return {result["channel"]: result for result in results}

    async def send_test_notification(self) -> Dict[str, Dict[str, str | bool]]:
        test_product = {
            "商品標題": "[測試通知] 蝦皮智慧監控",
            "目前售價": "0",
            "商品連結": "https://shopee.tw/",
        }
        return await self.send_notification(
            test_product,
            "這是一條測試通知，用於驗證推送渠道是否可用。",
        )

    async def _send_with_result(
        self,
        client: NotificationClient,
        product_data: Dict,
        reason: str,
    ) -> Dict[str, str | bool]:
        try:
            await client.send(product_data, reason)
            return {
                "channel": client.channel_key,
                "label": client.display_name,
                "success": True,
                "message": "傳送成功",
            }
        except Exception as exc:
            return {
                "channel": client.channel_key,
                "label": client.display_name,
                "success": False,
                "message": str(exc),
            }


def build_notification_service(
    settings: NotificationSettings | None = None,
) -> NotificationService:
    notification_settings = settings or load_notification_settings()
    return NotificationService(build_notification_clients(notification_settings))
