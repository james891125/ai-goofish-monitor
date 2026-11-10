"""
排程服務
負責管理定時任務的排程
"""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List

from src.core.cron_utils import build_cron_trigger
from src.domain.models.task import Task
from src.services.process_service import ProcessService


class SchedulerService:
    """排程服務"""

    def __init__(self, process_service: ProcessService):
        self.scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
        self.process_service = process_service

    def start(self):
        """啟動排程器"""
        if not self.scheduler.running:
            self.scheduler.start()
            print("排程器已啟動")

    def stop(self):
        """停止排程器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            print("排程器已停止")

    def get_next_run_time(self, task_id: int):
        job = self.scheduler.get_job(f"task_{task_id}")
        if job is None:
            return None

        next_run_time = getattr(job, "next_run_time", None)
        if next_run_time is not None:
            return next_run_time

        trigger = getattr(job, "trigger", None)
        if trigger is None or not hasattr(trigger, "get_next_fire_time"):
            return None

        try:
            now = datetime.now(self.scheduler.timezone)
            return trigger.get_next_fire_time(None, now)
        except Exception:
            return None

    async def reload_jobs(self, tasks: List[Task]):
        """重新載入所有定時任務"""
        print("正在重新載入定時任務...")
        self.scheduler.remove_all_jobs()

        for task in tasks:
            if task.enabled and task.cron:
                try:
                    trigger = build_cron_trigger(
                        task.cron,
                        timezone=self.scheduler.timezone,
                    )
                    self.scheduler.add_job(
                        self._run_task,
                        trigger=trigger,
                        args=[task.id, task.task_name],
                        id=f"task_{task.id}",
                        name=f"Scheduled: {task.task_name}",
                        replace_existing=True
                    )
                    print(f"  -> 已為任務 '{task.task_name}' 新增定時規則: '{task.cron}'")
                except ValueError as e:
                    print(f"  -> [警告] 任務 '{task.task_name}' 的 Cron 表示式無效: {e}")

        print("定時任務載入完成")

    async def _run_task(self, task_id: int, task_name: str):
        """執行定時任務"""
        print(f"定時任務觸發: 正在為任務 '{task_name}' 啟動爬蟲...")
        await self.process_service.start_task(task_id, task_name)
