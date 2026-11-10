"""
通知客戶端基類
定義通知客戶端的統一介面
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    price: str
    reason: str
    desktop_link: str
    notification_title: str
    content: str
    image_url: str | None


class NotificationClient(ABC):
    """通知客戶端抽象基類"""

    channel_key = "unknown"
    display_name = "未知渠道"

    def __init__(self, enabled: bool = False):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        """檢查客戶端是否啟用"""
        return self._enabled

    @abstractmethod
    async def send(self, product_data: Dict, reason: str) -> bool:
        """
        傳送通知

        Args:
            product_data: 商品資料
            reason: 推薦原因

        Returns:
            是否傳送成功
        """
        raise NotImplementedError

    def _build_message(self, product_data: Dict, reason: str) -> NotificationMessage:
        """格式化訊息內容"""
        title = product_data.get('商品標題', 'N/A')
        price = product_data.get('目前售價', 'N/A')
        desktop_link = product_data.get('商品連結', '#')

        content_lines = [
            f"價格: {price}",
            f"原因: {reason}",
            f"連結: {desktop_link}",
        ]

        short_title = title[:30]
        suffix = "..." if len(title) > 30 else ""
        notification_title = f"🚨 新推薦! {short_title}{suffix}"

        main_image = product_data.get('商品主圖連結')
        if not main_image:
            image_list = product_data.get('商品圖片列表', [])
            if image_list:
                main_image = image_list[0]

        return NotificationMessage(
            title=title,
            price=price,
            reason=reason,
            desktop_link=desktop_link,
            notification_title=notification_title,
            content="\n".join(content_lines),
            image_url=main_image,
        )
