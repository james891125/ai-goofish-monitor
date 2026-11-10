"""
登入狀態管理路由
"""
import os
import json
import aiofiles
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/login-state", tags=["login-state"])


class LoginStateUpdate(BaseModel):
    """登入狀態更新模型"""
    content: str


@router.post("", response_model=dict)
async def update_login_state(
    data: LoginStateUpdate,
):
    """接收前端傳送的登入狀態JSON字串，並儲存到 shopee_state.json"""
    state_file = "shopee_state.json"

    try:
        # 驗證是否是有效的JSON
        json.loads(data.content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="提供的內容不是有效的JSON格式。")

    try:
        async with aiofiles.open(state_file, 'w', encoding='utf-8') as f:
            await f.write(data.content)
        return {"message": f"登入狀態檔案 '{state_file}' 已成功更新。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入登入狀態檔案時出錯: {e}")


@router.delete("", response_model=dict)
async def delete_login_state():
    """刪除 shopee_state.json 檔案"""
    state_file = "shopee_state.json"

    if os.path.exists(state_file):
        try:
            os.remove(state_file)
            return {"message": "登入狀態檔案已成功刪除。"}
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"刪除登入狀態檔案時出錯: {e}")

    return {"message": "登入狀態檔案不存在，無需刪除。"}
