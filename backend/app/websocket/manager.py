"""WebSocket 连接管理与跨页面售后状态同步。"""
from typing import Dict, Set, Optional
from fastapi import WebSocket
from datetime import datetime, timezone


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Dict[str, WebSocket]] = {}
        self.admin_connections: Dict[int, WebSocket] = {}
        self.thread_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect_user(self, websocket: WebSocket, user_id: int, thread_id: str):
        await websocket.accept()
        self.active_connections.setdefault(user_id, {})[thread_id] = websocket
        self.thread_subscribers.setdefault(thread_id, set()).add(websocket)

    async def connect_admin(self, websocket: WebSocket, admin_id: int):
        await websocket.accept()
        self.admin_connections[admin_id] = websocket

    def disconnect_user(self, user_id: int, thread_id: str):
        user_connections = self.active_connections.get(user_id, {})
        websocket = user_connections.pop(thread_id, None)
        if websocket:
            self.thread_subscribers.get(thread_id, set()).discard(websocket)
        if user_id in self.active_connections and not self.active_connections[user_id]:
            del self.active_connections[user_id]

    def disconnect_admin(self, admin_id: int):
        self.admin_connections.pop(admin_id, None)

    async def send_to_thread(self, thread_id: str, message: dict):
        for websocket in list(self.thread_subscribers.get(thread_id, set())):
            try:
                await websocket.send_json(message)
            except Exception:
                self.thread_subscribers.get(thread_id, set()).discard(websocket)

    async def send_to_user(self, user_id: int, message: dict):
        for thread_id, websocket in list(self.active_connections.get(user_id, {}).items()):
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect_user(user_id, thread_id)

    async def broadcast_to_admins(self, message: dict):
        for admin_id, websocket in list(self.admin_connections.items()):
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect_admin(admin_id)

    async def notify_after_sales_change(self, thread_id: str, after_sales: dict, message: Optional[str] = None, user_id: Optional[int] = None):
        event = {
            "type": "after_sales_updated", "thread_id": thread_id,
            "after_sales_id": after_sales.get("after_sales_id"),
            "after_sales_status": after_sales.get("after_sales_status"),
            "after_sales_status_label": after_sales.get("after_sales_status_label"),
            "data": after_sales, "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if thread_id:
            await self.send_to_thread(thread_id, event)
        if user_id:
            await self.send_to_user(user_id, event)
        await self.broadcast_to_admins(event)

    async def notify_status_change(self, thread_id: str, status: str, data: Optional[dict] = None):
        event = {"type": "status_change", "thread_id": thread_id, "status": status, "data": data or {}, "timestamp": datetime.now(timezone.utc).isoformat()}
        await self.send_to_thread(thread_id, event)
        if status == "WAITING_ADMIN":
            await self.broadcast_to_admins({"type": "new_audit_task", "thread_id": thread_id, "data": data or {}, "timestamp": event["timestamp"]})


manager = ConnectionManager()
