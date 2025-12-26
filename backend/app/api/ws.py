import asyncio
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, Set[WebSocket]] = {"logs": set(), "decisions": set()}

    async def connect(self, label: str, websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"message": f"connected to {label} stream"})
        self.connections.setdefault(label, set()).add(websocket)

    def disconnect(self, label: str, websocket: WebSocket):
        if websocket in self.connections.get(label, set()):
            self.connections[label].remove(websocket)

    async def broadcast(self, label: str, payload):
        for ws in list(self.connections.get(label, set())):
            try:
                await ws.send_json(payload)
            except WebSocketDisconnect:
                self.disconnect(label, ws)


manager = ConnectionManager()


def _queue_broadcast(label: str, payload):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running():
        loop.create_task(manager.broadcast(label, payload))


def notify_log(payload):
    _queue_broadcast("logs", payload)


def notify_decision(payload):
    _queue_broadcast("decisions", payload)


@router.websocket("/ws/logs")
async def logs_socket(websocket: WebSocket):
    await manager.connect("logs", websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("logs", websocket)


@router.websocket("/ws/decisions")
async def decisions_socket(websocket: WebSocket):
    await manager.connect("decisions", websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("decisions", websocket)
