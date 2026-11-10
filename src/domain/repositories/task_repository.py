"""
任務倉儲層
負責任務資料的持久化操作
"""
from typing import List, Optional
from abc import ABC, abstractmethod
import json
import aiofiles
from src.domain.models.task import Task


class TaskRepository(ABC):
    """任務倉儲介面"""

    @abstractmethod
    async def find_all(self) -> List[Task]:
        """獲取所有任務"""
        pass

    @abstractmethod
    async def find_by_id(self, task_id: int) -> Optional[Task]:
        """根據ID獲取任務"""
        pass

    @abstractmethod
    async def save(self, task: Task) -> Task:
        """儲存任務（建立或更新）"""
        pass

    @abstractmethod
    async def delete(self, task_id: int) -> bool:
        """刪除任務"""
        pass
