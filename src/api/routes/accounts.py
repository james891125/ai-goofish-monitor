"""
蝦皮帳號管理路由
"""
import json
import os
import re
import aiofiles
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from src.infrastructure.config.env_manager import env_manager
from src.services.shopee_login_state import (
    LoginStateError,
    normalize_login_state,
    summarize_login_state,
)


router = APIRouter(prefix="/api/accounts", tags=["accounts"])

ACCOUNT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


DEFAULT_ACCOUNT_NAME = "shopee"


class AccountCreate(BaseModel):
    name: Optional[str] = None
    content: str
    # 同名帳號已存在時直接覆蓋（重新貼上新的 Cookie）
    overwrite: bool = False


class AccountUpdate(BaseModel):
    content: str


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return value[1:-1]
    return value


def _state_dir() -> str:
    raw = env_manager.get_value("ACCOUNT_STATE_DIR", "state") or "state"
    return _strip_quotes(raw.strip())


def _ensure_state_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed or not ACCOUNT_NAME_RE.match(trimmed):
        raise HTTPException(status_code=400, detail="帳號名稱只能包含字母、數字、下劃線或短橫線。")
    return trimmed


def _account_path(name: str) -> str:
    filename = f"{name}.json"
    return os.path.join(_state_dir(), filename)


def _prepare_content(content: str) -> str:
    """檢查並整理貼上的登入狀態，回傳要寫入檔案的 JSON 文字。"""
    try:
        state = normalize_login_state(content)
    except LoginStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return json.dumps(state, ensure_ascii=False, indent=2)


def _describe_account(name: str, path: str) -> dict:
    info = {"name": name, "path": path}
    try:
        with open(path, "r", encoding="utf-8") as f:
            info.update(summarize_login_state(json.load(f)))
        info["updated_at"] = datetime.fromtimestamp(os.path.getmtime(path)).isoformat(
            timespec="seconds"
        )
    except (OSError, ValueError):
        info.update({"cookie_count": 0, "logged_in": False, "invalid": True})
    return info


@router.get("", response_model=List[dict])
async def list_accounts():
    state_dir = _state_dir()
    if not os.path.isdir(state_dir):
        return []
    files = [f for f in os.listdir(state_dir) if f.endswith(".json")]
    accounts = []
    for filename in sorted(files):
        name = filename[:-5]
        accounts.append(_describe_account(name, os.path.join(state_dir, filename)))
    return accounts


@router.get("/{name}", response_model=dict)
async def get_account(name: str):
    account_name = _validate_name(name)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="帳號不存在")
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return {"name": account_name, "path": path, "content": content}


@router.post("", response_model=dict)
async def create_account(data: AccountCreate):
    account_name = _validate_name(data.name or DEFAULT_ACCOUNT_NAME)
    content = _prepare_content(data.content)
    state_dir = _state_dir()
    _ensure_state_dir(state_dir)
    path = _account_path(account_name)
    existed = os.path.exists(path)
    if existed and not data.overwrite:
        raise HTTPException(status_code=409, detail="帳號已存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
    return {
        "message": "帳號已更新" if existed else "帳號已新增",
        **_describe_account(account_name, path),
    }


@router.put("/{name}", response_model=dict)
async def update_account(name: str, data: AccountUpdate):
    account_name = _validate_name(name)
    content = _prepare_content(data.content)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="帳號不存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)
    return {"message": "帳號已更新", **_describe_account(account_name, path)}


@router.delete("/{name}", response_model=dict)
async def delete_account(name: str):
    account_name = _validate_name(name)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="帳號不存在")
    os.remove(path)
    return {"message": "帳號已刪除"}
