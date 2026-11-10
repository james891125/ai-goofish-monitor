"""
任務生成作業模型
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from src.domain.models.task import Task


TaskGenerationStatus = Literal["queued", "running", "completed", "failed"]
TaskGenerationStepStatus = Literal["pending", "running", "completed", "failed"]


class TaskGenerationStep(BaseModel):
    """單個任務生成步驟"""

    key: str
    label: str
    status: TaskGenerationStepStatus = "pending"
    message: str = ""


class TaskGenerationJob(BaseModel):
    """任務生成作業"""

    job_id: str
    task_name: str
    status: TaskGenerationStatus = "queued"
    message: str = "任務已排隊，等待開始。"
    current_step: Optional[str] = None
    steps: List[TaskGenerationStep] = Field(default_factory=list)
    task: Optional[Task] = None
    error: Optional[str] = None
