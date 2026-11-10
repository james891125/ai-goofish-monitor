"""Single-process asyncio worker and APScheduler runtime (Asia/Taipei)."""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.core.cron_utils import build_cron_trigger
from src.providers.base import ProviderError
from src.services.product_monitor import ProductMonitor


class ShopeeRuntime:
    def __init__(self, repository):
        self.repository=repository
        self.monitor=ProductMonitor(repository)
        self.scheduler=AsyncIOScheduler(timezone='Asia/Taipei')
        self.jobs: dict[int,asyncio.Task]={}

    async def start_task(self, task_id):
        task=self.repository.get_task(task_id)
        if not task:
            raise ProviderError('not_found','找不到任務。')
        if not task.enabled:
            raise ProviderError('task_disabled','任務已停用。')
        if task_id in self.jobs and not self.jobs[task_id].done():
            raise ProviderError('already_running','任務正在執行。')
        job=asyncio.create_task(self.monitor.run(task))
        self.jobs[task_id]=job
        job.add_done_callback(lambda done: self._finished(task_id,done))

    def _finished(self, task_id, job):
        if self.jobs.get(task_id) is job:
            self.jobs.pop(task_id,None)
        if not job.cancelled():
            job.exception() # Consume typed lock failures; do not leak raw exceptions to logs.

    def reload(self):
        self.scheduler.remove_all_jobs()
        for task in self.repository.tasks():
            if task.enabled and task.cron and task.provider != 'browser_experiment':
                self.scheduler.add_job(self.start_task,build_cron_trigger(task.cron,timezone='Asia/Taipei'),
                                       args=[task.id],id=f'shopee_{task.id}',max_instances=1,
                                       coalesce=True,misfire_grace_time=60)

    def start(self):
        self.reload(); self.scheduler.start()

    async def close(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        jobs=list(self.jobs.values())
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)

    def task_payload(self, task):
        job=self.scheduler.get_job(f'shopee_{task.id}')
        next_run=getattr(job,'next_run_time',None) if job else None
        return dict(task.model_dump(),is_running=task.id in self.jobs,next_run_at=next_run.isoformat() if next_run else None)
