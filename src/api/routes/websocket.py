"""
WebSocket 路由
提供即時通訊功能
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Set


router = APIRouter()

# 全域 WebSocket 連線管理
active_connections: Set[WebSocket] = set()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    """WebSocket 端點"""
    # 接受連線
    await websocket.accept()
    active_connections.add(websocket)

    try:
        # 保持連線並接收訊息
        while True:
            # 接收客戶端訊息（如果有的話）
            data = await websocket.receive_text()
            # 這裡可以處理客戶端傳送的訊息
            # 目前我們主要用於服務端推送，所以暫時不處理
    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket 錯誤: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)


async def broadcast_message(message_type: str, data: dict):
    """向所有連線的客戶端廣播訊息"""
    message = {
        "type": message_type,
        "data": data
    }

    # 移除已斷開的連線
    disconnected = set()

    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            disconnected.add(connection)

    # 清理斷開的連線
    for connection in disconnected:
        active_connections.discard(connection)
