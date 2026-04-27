"""WebSocket 端点"""

from typing import Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.agent.memory.manager import MemoryManager
from app.agent.autogen.session_manager import session_manager
import json

router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.memory_managers: Dict[str, MemoryManager] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.memory_managers[session_id] = MemoryManager(session_id)

    def disconnect(self, session_id: str) -> None:
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        if session_id in self.memory_managers:
            del self.memory_managers[session_id]

    async def send_message(self, session_id: str, message: str) -> None:
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_text(message)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections.values():
            await connection.send_text(message)


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket 端点

    支持实时 Agent 交互。
    """
    await manager.connect(websocket, session_id)

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "连接已建立",
        })

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type", "execute")
            task = message.get("task", "")
            context = message.get("context", {})

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            memory_manager = manager.memory_managers.get(session_id)
            if memory_manager:
                await memory_manager.add_user_message(task)

            events = []

            def on_event(event_type: str, data: Dict[str, Any]):
                events.append({"type": event_type, "data": data})

            try:
                result = await session_manager.execute(
                    session_id=session_id,
                    task=task,
                    context={**context, "session_id": session_id},
                    on_event=on_event,
                )

                if memory_manager:
                    await memory_manager.add_assistant_message(str(result.get("summary", "")))

                await websocket.send_json({
                    "type": "result",
                    "success": result.get("success", False),
                    "result": result,
                    "events": events,
                })

            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "error": str(e),
                })

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass
        manager.disconnect(session_id)


@router.get("/ws/list")
async def list_connections() -> Dict[str, Any]:
    """列出所有活跃连接"""
    return {
        "active_connections": len(manager.active_connections),
        "sessions": list(manager.active_connections.keys()),
    }
