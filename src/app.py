"""
新架構的主應用入口
整合所有路由和服務
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.routes import (
    dashboard,
    tasks,
    logs,
    settings,
    prompts,
    results,
    login_state,
    websocket,
    accounts,
)
from src.api.dependencies import (
    set_process_service,
    set_scheduler_service,
    set_task_generation_service,
)
from src.services.task_service import TaskService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_log_cleanup_service import cleanup_task_logs
from src.services.task_generation_service import TaskGenerationService
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.infrastructure.config.settings import settings as app_settings


# 全域服務實例
process_service = ProcessService()
scheduler_service = SchedulerService(process_service)
task_generation_service = TaskGenerationService()


async def _sync_task_runtime_status(task_id: int, is_running: bool) -> None:
    task_service = TaskService(SqliteTaskRepository())
    task = await task_service.get_task(task_id)
    if not task or task.is_running == is_running:
        return
    await task_service.update_task_status(task_id, is_running)
    await websocket.broadcast_message(
        "task_status_changed",
        {"id": task_id, "is_running": is_running},
    )


process_service.set_lifecycle_hooks(
    on_started=lambda task_id: _sync_task_runtime_status(task_id, True),
    on_stopped=lambda task_id: _sync_task_runtime_status(task_id, False),
)

# 設定全域 ProcessService 實例供依賴注入使用
set_process_service(process_service)
set_scheduler_service(scheduler_service)
set_task_generation_service(task_generation_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期管理"""
    # 啟動時
    print("正在啟動應用...")
    bootstrap_sqlite_storage()
    cleanup_task_logs(keep_days=app_settings.task_log_retention_days)

    # 重置所有任務狀態為停止
    task_repo = SqliteTaskRepository()
    task_service = TaskService(task_repo)
    tasks_list = await task_service.get_all_tasks()

    for task in tasks_list:
        if task.is_running:
            await task_service.update_task_status(task.id, False)

    # 載入定時任務
    await scheduler_service.reload_jobs(tasks_list)
    scheduler_service.start()

    print("應用啟動完成")

    yield

    # 關閉時
    print("正在關閉應用...")
    scheduler_service.stop()
    await process_service.stop_all()
    print("應用已關閉")


# 建立 FastAPI 應用
app = FastAPI(
    title="蝦皮智慧監控機器人",
    description="基於AI的蝦皮商品監控系統",
    version="2.0.0",
    lifespan=lifespan
)

# 註冊路由
app.include_router(tasks.router)
app.include_router(dashboard.router)
app.include_router(logs.router)
app.include_router(settings.router)
app.include_router(prompts.router)
app.include_router(results.router)
app.include_router(login_state.router)
app.include_router(websocket.router)
app.include_router(accounts.router)

# 掛載靜態檔案
# 舊的靜態檔案目錄（用於截圖等）
app.mount("/static", StaticFiles(directory="static"), name="static")

# 掛載 Vue 3 前端構建產物
# 注意：需要在所有 API 路由之後掛載，以避免覆蓋 API 路由
import os
if os.path.exists("dist"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")


# 健康檢查端點
@app.get("/health")
async def health_check():
    """健康檢查（無需認證）"""
    return {"status": "healthy", "message": "服務正常執行"}


# 認證狀態檢查端點
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/status")
async def auth_status(payload: LoginRequest):
    """檢查認證狀態"""
    # 帳密留空代表尚未設定，不能讓空白帳密直接登入
    if not app_settings.web_username or not app_settings.web_password:
        raise HTTPException(status_code=401, detail="尚未設定登入帳號密碼，請先執行 setup_env.py")
    if payload.username == app_settings.web_username and payload.password == app_settings.web_password:
        return {"authenticated": True, "username": payload.username}
    raise HTTPException(status_code=401, detail="認證失敗")


# 主頁路由 - 服務 Vue 3 SPA
from fastapi.responses import JSONResponse

@app.get("/")
async def read_root(request: Request):
    """提供 Vue 3 SPA 的主頁面"""
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    else:
        return JSONResponse(
            status_code=500,
            content={"error": "前端構建產物不存在，請先執行 cd web-ui && npm run build"}
        )


# Catch-all 路由 - 處理所有前端路由（必須放在最後）
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """
    Catch-all 路由，將所有非 API 請求重定向到 index.html
    這樣可以支援 Vue Router 的 HTML5 History 模式
    """
    # 如果請求的是靜態資源（如 favicon.ico），返回 404
    if full_path.endswith(('.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.css', '.js', '.json')):
        return JSONResponse(status_code=404, content={"error": "資源未找到"})

    # 其他所有路徑都返回 index.html，讓前端路由處理
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    else:
        return JSONResponse(
            status_code=500,
            content={"error": "前端構建產物不存在，請先執行 cd web-ui && npm run build"}
        )


if __name__ == "__main__":
    import uvicorn
    from src.infrastructure.config.settings import settings

    print(f"啟動新架構應用，連接埠: {app_settings.server_port}")
    # 本機執行時只開放給這台電腦；Docker 內才需要對外監聽
    default_host = "0.0.0.0" if os.getenv("RUNNING_IN_DOCKER", "").lower() == "true" else "127.0.0.1"
    uvicorn.run(
        app,
        host=os.getenv("SERVER_HOST", "").strip() or default_host,
        port=app_settings.server_port,
    )
