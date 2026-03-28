from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.models.schemas import EventMessage
from app.services.event_store_service import event_store_service


class EventBus:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._task_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            if task_id:
                self._task_connections[task_id].add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            for sockets in self._task_connections.values():
                sockets.discard(websocket)

    async def publish(self, message: EventMessage, task_id: str | None = None) -> None:
        event_store_service.append(message=message, task_id=task_id)
        payload = message.model_dump(mode='json')
        async with self._lock:
            targets = set(self._connections)
            if task_id:
                targets.update(self._task_connections.get(task_id, set()))

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


event_bus = EventBus()
