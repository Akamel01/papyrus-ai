"""
SME Dashboard — WebSocket Connection Manager

Manages connected clients, broadcasts events, streams logs.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger("dashboard.ws")


class WSManager:
    """
    Manages WebSocket connections.
    Supports: broadcast to all, filtered log streaming, graceful disconnect.
    """

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info(f"[WS] Client connected ({len(self._connections)} total)")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections.discard(ws)
        logger.info(f"[WS] Client disconnected ({len(self._connections)} total)")

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        if not self._connections:
            return

        payload = json.dumps(message)
        dead = []

        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)
