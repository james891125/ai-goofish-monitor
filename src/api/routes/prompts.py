"""
Prompt 管理路由
"""
import os
import aiofiles
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/prompts", tags=["prompts"])

_PROMPTS_DIR = Path("prompts").resolve()


def _safe_prompt_path(filename: str) -> Path:
    """回傳经過 containment 檢查的绝對路径，防止任意 OS 上的路径穿越。"""
    try:
        resolved = (_PROMPTS_DIR / filename).resolve()
        resolved.relative_to(_PROMPTS_DIR)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="無效的檔案名")
    return resolved


class PromptUpdate(BaseModel):
    """Prompt 更新模型"""
    content: str


@router.get("")
async def list_prompts():
    """列出所有 prompt 檔案"""
    if not _PROMPTS_DIR.is_dir():
        return []
    return [f for f in os.listdir(_PROMPTS_DIR) if f.endswith(".txt")]


@router.get("/{filename}")
async def get_prompt(filename: str):
    """取得 prompt 檔案內容"""
    filepath = _safe_prompt_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Prompt 檔案找不到")

    async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
        content = await f.read()
    return {"filename": filepath.name, "content": content}


@router.put("/{filename}")
async def update_prompt(
    filename: str,
    prompt_update: PromptUpdate,
):
    """更新 prompt 檔案內容"""
    filepath = _safe_prompt_path(filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Prompt 檔案找不到")

    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(prompt_update.content)
        return {"message": f"Prompt 檔案 '{filepath.name}' 更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入檔案時出错: {e}")
