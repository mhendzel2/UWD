from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


async def _send_initial(socket: WebSocket, label: str):
    await socket.send_json({"message": f"connected to {label} stream"})


@router.websocket("/ws/logs")
async def logs_socket(websocket: WebSocket):
    await websocket.accept()
    await _send_initial(websocket, "logs")
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        return


@router.websocket("/ws/decisions")
async def decisions_socket(websocket: WebSocket):
    await websocket.accept()
    await _send_initial(websocket, "decisions")
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        return
