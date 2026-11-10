"""
任務管理路由
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import os
import aiofiles
from src.api.dependencies import (
    get_process_service,
    get_scheduler_service,
    get_task_generation_service,
    get_task_service,
)
from src.services.task_service import TaskService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_generation_service import TaskGenerationService
from src.services.task_generation_runner import (
    build_task_create,
    run_ai_generation_job,
)
from src.services.task_payloads import serialize_task, serialize_tasks
from src.domain.models.task import TaskCreate, TaskUpdate, TaskGenerateRequest
from src.prompt_utils import generate_criteria
from src.utils import resolve_task_log_path
from src.services.account_strategy_service import normalize_account_strategy
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.price_history_service import delete_price_snapshots
from src.services.result_storage_service import delete_result_file_records
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

async def _reload_scheduler_if_needed(
    task_service: TaskService,
    scheduler_service: SchedulerService,
):
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)


def _has_keyword_rules(rules) -> bool:
    return bool(rules and len(rules) > 0)


def _validate_final_account_strategy(existing_task, task_update: TaskUpdate) -> None:
    account_state_file = (
        task_update.account_state_file
        if task_update.account_state_file is not None
        else existing_task.account_state_file
    )
    account_strategy = normalize_account_strategy(
        task_update.account_strategy,
        account_state_file,
    )
    task_update.account_strategy = account_strategy
    if account_strategy == "fixed" and not account_state_file:
        raise HTTPException(status_code=400, detail="固定帳號模式下必須選擇帳號。")
@router.get("", response_model=List[dict])
async def get_tasks(
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """獲取所有任務"""
    tasks = await service.get_all_tasks()
    return serialize_tasks(tasks, scheduler_service)
@router.get("/{task_id}", response_model=dict)
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """獲取單個任務"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務未找到")
    return serialize_task(task, scheduler_service)
@router.post("/", response_model=dict)
async def create_task(
    task_create: TaskCreate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """建立新任務"""
    task = await service.create_task(task_create)
    await _reload_scheduler_if_needed(service, scheduler_service)
    return {"message": "任務建立成功", "task": serialize_task(task, scheduler_service)}
@router.post("/generate", response_model=dict)
async def generate_task(
    req: TaskGenerateRequest,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
):
    """建立任務。AI模式會生成分析標準，關鍵詞模式直接儲存規則。"""
    print(f"收到任務生成請求: {req.task_name}，模式: {req.decision_mode}")

    try:
        mode = req.decision_mode or "ai"
        if mode == "ai":
            job = await generation_service.create_job(req.task_name)
            generation_service.track(
                run_ai_generation_job(
                    job_id=job.job_id,
                    req=req,
                    task_service=service,
                    scheduler_service=scheduler_service,
                    generation_service=generation_service,
                )
            )
            return JSONResponse(
                status_code=202,
                content={
                    "message": "AI 任務生成已開始。",
                    "job": job.model_dump(mode="json"),
                },
            )

        task = await service.create_task(build_task_create(req, ""))
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任務建立成功。", "task": serialize_task(task, scheduler_service)}

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"AI任務生成API發生未知錯誤: {str(e)}"
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)
@router.get("/generate-jobs/{job_id}", response_model=dict)
async def get_task_generation_job(
    job_id: str,
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
):
    """獲取任務生成作業狀態"""
    job = await generation_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任務生成作業未找到")
    return {"job": job.model_dump(mode="json")}
@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """更新任務"""
    try:
        existing_task = await service.get_task(task_id)
        if not existing_task:
            raise HTTPException(status_code=404, detail="任務未找到")
        _validate_final_account_strategy(existing_task, task_update)

        current_mode = getattr(existing_task, "decision_mode", "ai") or "ai"
        target_mode = task_update.decision_mode or current_mode
        description_changed = (
            task_update.description is not None
            and task_update.description != existing_task.description
        )
        switched_to_ai = current_mode != "ai" and target_mode == "ai"

        if target_mode == "keyword":
            final_rules = (
                task_update.keyword_rules
                if task_update.keyword_rules is not None
                else getattr(existing_task, "keyword_rules", [])
            )
            if not _has_keyword_rules(final_rules):
                raise HTTPException(status_code=400, detail="關鍵詞模式下至少需要一個關鍵詞。")
        if target_mode == "ai" and (description_changed or switched_to_ai):
            print(f"檢測到任務 {task_id} 需要重新整理 AI 標準檔案，開始重新生成...")
            try:
                description_for_ai = (
                    task_update.description
                    if task_update.description is not None
                    else existing_task.description
                )
                if not str(description_for_ai or "").strip():
                    raise HTTPException(status_code=400, detail="AI 模式下詳細需求不能為空。")
                safe_keyword = "".join(
                    c for c in existing_task.keyword.lower().replace(' ', '_')
                    if c.isalnum() or c in "_-"
                ).rstrip()
                output_filename = f"prompts/{safe_keyword}_criteria.txt"
                print(f"目標檔案路徑: {output_filename}")
                print("開始呼叫 AI 生成新的分析標準...")
                generated_criteria = await generate_criteria(
                    user_description=description_for_ai,
                    reference_file_path="prompts/macbook_criteria.txt"
                )
                if not generated_criteria or len(generated_criteria.strip()) == 0:
                    print("AI 返回的內容為空")
                    raise HTTPException(status_code=500, detail="AI 未能生成分析標準，返回內容為空。")
                print(f"儲存新的分析標準到: {output_filename}")
                os.makedirs("prompts", exist_ok=True)
                async with aiofiles.open(output_filename, 'w', encoding='utf-8') as f:
                    await f.write(generated_criteria)
                print(f"新的分析標準已儲存")
                task_update.ai_prompt_criteria_file = output_filename
                print(f"已更新 ai_prompt_criteria_file 欄位為: {output_filename}")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"重新生成 criteria 檔案時出錯: {str(e)}"
                print(error_msg)
                import traceback
                print(traceback.format_exc())
                raise HTTPException(status_code=500, detail=error_msg)
        task = await service.update_task(task_id, task_update)
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任務更新成功", "task": serialize_task(task, scheduler_service)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """刪除任務"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務未找到")

    await process_service.stop_task(task_id)
    success = await service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任務未找到")
    await _reload_scheduler_if_needed(service, scheduler_service)
    try:
        keyword = (task.keyword or "").strip()
        if keyword:
            remaining_tasks = await service.get_all_tasks()
            keyword_still_in_use = any(
                (remaining_task.keyword or "").strip() == keyword
                for remaining_task in remaining_tasks
            )
            if not keyword_still_in_use:
                await delete_result_file_records(build_result_filename(keyword))
                delete_price_snapshots(keyword)
    except Exception as e:
        print(f"刪除任務結果檔案時出錯: {e}")

    try:
        log_file_path = resolve_task_log_path(task_id, task.task_name)
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
    except Exception as e:
        print(f"刪除任務日誌檔案時出錯: {e}")
    return {"message": "任務刪除成功"}
@router.post("/start/{task_id}", response_model=dict)
async def start_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
):
    """啟動單個任務"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務未找到")
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任務已被禁用，無法啟動")
    if task.is_running:
        raise HTTPException(status_code=400, detail="任務已在執行中")
    success = await process_service.start_task(task_id, task.task_name)
    if not success:
        raise HTTPException(status_code=500, detail="啟動任務失敗")
    return {"message": f"任務 '{task.task_name}' 已啟動"}
@router.post("/stop/{task_id}", response_model=dict)
async def stop_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
):
    """停止單個任務"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務未找到")
    await process_service.stop_task(task_id)
    return {"message": f"任務ID {task_id} 已傳送停止訊號"}
