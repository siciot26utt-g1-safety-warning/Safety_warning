#quản lý kết nối websocket từ trình duyệt dashboard thông qua hub
"""Broadcast WebSocket tới Dashboard (PLAN.md bước 1.4)."""

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("ws")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        log.info("Dashboard kết nối (%d client)", len(self.clients))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _send(self, ws: WebSocket, text: str) -> None:
        try:
            await ws.send_text(text)
        except Exception:
            self.disconnect(ws)

    def broadcast(self, message: dict) -> None:
        """Gọi được từ thread MQTT — marshal về event loop của FastAPI."""
        if not self.clients or self.loop is None:
            return
        text = json.dumps(message, default=str)
        for ws in list(self.clients):
            asyncio.run_coroutine_threadsafe(self._send(ws, text), self.loop)


hub = Hub()
