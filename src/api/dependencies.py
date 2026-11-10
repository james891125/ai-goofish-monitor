"""
FastAPI 依賴注入
提供服務實例的建立和管理
"""
from fastapi import Depends
from src.services.task_service import TaskService
from src.services.notification_service import NotificationService, build_notification_service
from src.services.ai_service import AIAnalysisService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_generation_service import TaskGenerationService
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.infrastructure.external.ai_client import AIClient


# 全域 ProcessService 實例（將在 app.py 中設定）
_process_service_instance = None
_scheduler_service_instance = None
_task_generation_service_instance = None


def set_process_service(service: ProcessService):
    """設定全域 ProcessService 實例"""
    global _process_service_instance
    _process_service_instance = service


def set_scheduler_service(service: SchedulerService):
    """設定全域 SchedulerService 實例"""
    global _scheduler_service_instance
    _scheduler_service_instance = service


def set_task_generation_service(service: TaskGenerationService):
    """設定全域 TaskGenerationService 實例"""
    global _task_generation_service_instance
    _task_generation_service_instance = service


# 服務依賴注入
def get_task_service() -> TaskService:
    """獲取任務管理服務實例"""
    repository = SqliteTaskRepository()
    return TaskService(repository)


def get_notification_service() -> NotificationService:
    """獲取通知服務實例"""
    return build_notification_service()


def get_ai_service() -> AIAnalysisService:
    """獲取AI分析服務實例"""
    ai_client = AIClient()
    return AIAnalysisService(ai_client)


def get_process_service() -> ProcessService:
    """獲取程序管理服務實例"""
    if _process_service_instance is None:
        raise RuntimeError("ProcessService 未初始化")
    return _process_service_instance


def get_scheduler_service() -> SchedulerService:
    """獲取排程服務實例"""
    if _scheduler_service_instance is None:
        raise RuntimeError("SchedulerService 未初始化")
    return _scheduler_service_instance


def get_task_generation_service() -> TaskGenerationService:
    """獲取任務生成作業服務實例"""
    if _task_generation_service_instance is None:
        raise RuntimeError("TaskGenerationService 未初始化")
    return _task_generation_service_instance
