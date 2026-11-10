"""
任務生成作業服務
"""
import asyncio
from copy import deepcopy
import threading
from typing import Awaitable, Dict, Iterable, Optional
from uuid import uuid4

from src.domain.models.task import Task
from src.domain.models.task_generation import TaskGenerationJob, TaskGenerationStep

DEFAULT_GENERATION_STEPS: tuple[tuple[str, str], ...] = (
    ("prepare", "接收建立請求"),
    ("reference", "讀取參考檔案"),
    ("prompt", "構建提示詞"),
    ("llm", "呼叫 AI 生成標準"),
    ("persist", "儲存分析標準"),
    ("task", "建立任務記錄"),
)


class TaskGenerationService:
    """管理 AI 任務生成的後臺作業狀態"""

    def __init__(self, step_specs: Iterable[tuple[str, str]] = DEFAULT_GENERATION_STEPS):
        self._step_specs = tuple(step_specs)
        self._jobs: Dict[str, TaskGenerationJob] = {}
        self._lock = threading.Lock()
        self._workers: set[threading.Thread] = set()

    async def create_job(self, task_name: str) -> TaskGenerationJob:
        job = TaskGenerationJob(
            job_id=uuid4().hex,
            task_name=task_name,
            steps=[
                TaskGenerationStep(key=key, label=label)
                for key, label in self._step_specs
            ],
        )
        with self._lock:
            self._jobs[job.job_id] = job
            return deepcopy(job)

    async def get_job(self, job_id: str) -> Optional[TaskGenerationJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return deepcopy(job)

    def track(self, coroutine: Awaitable[None]) -> None:
        thread: Optional[threading.Thread] = None

        def runner() -> None:
            try:
                asyncio.run(coroutine)
            finally:
                if thread is None:
                    return
                with self._lock:
                    self._workers.discard(thread)

        thread = threading.Thread(target=runner, daemon=True)
        with self._lock:
            self._workers.add(thread)
        thread.start()

    async def advance(self, job_id: str, step_key: str, message: str) -> TaskGenerationJob:
        with self._lock:
            job = self._require_job(job_id)
            target_index = self._find_step_index(job, step_key)
            job.status = "running"
            job.current_step = step_key
            job.message = message
            for index, step in enumerate(job.steps):
                if step.status == "failed":
                    continue
                if index < target_index:
                    step.status = "completed"
                elif index == target_index:
                    step.status = "running"
                    step.message = message
                elif step.status != "pending":
                    step.status = "pending"
                    step.message = ""
            return deepcopy(job)

    async def complete(self, job_id: str, task: Task, message: str) -> TaskGenerationJob:
        with self._lock:
            job = self._require_job(job_id)
            job.status = "completed"
            job.current_step = None
            job.message = message
            job.error = None
            job.task = task
            for step in job.steps:
                if step.status != "failed":
                    step.status = "completed"
            return deepcopy(job)

    async def fail(
        self,
        job_id: str,
        error: str,
        step_key: Optional[str] = None,
    ) -> TaskGenerationJob:
        with self._lock:
            job = self._require_job(job_id)
            failed_step = step_key or job.current_step
            job.status = "failed"
            job.error = error
            job.message = error
            job.current_step = failed_step
            if failed_step:
                step = self._find_step(job, failed_step)
                if step:
                    step.status = "failed"
                    step.message = error
            return deepcopy(job)

    def _require_job(self, job_id: str) -> TaskGenerationJob:
        job = self._jobs.get(job_id)
        if not job:
            raise KeyError(f"任務生成作業不存在: {job_id}")
        return job

    def _find_step(self, job: TaskGenerationJob, step_key: str) -> Optional[TaskGenerationStep]:
        for step in job.steps:
            if step.key == step_key:
                return step
        return None

    def _find_step_index(self, job: TaskGenerationJob, step_key: str) -> int:
        for index, step in enumerate(job.steps):
            if step.key == step_key:
                return index
        raise KeyError(f"未知的任務生成步驟: {step_key}")
