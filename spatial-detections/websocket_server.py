import asyncio
import json
import threading
from typing import Callable, Optional, Set


class WebSocketBridge:
    def __init__(self, host: str = "0.0.0.0", port: int = 8001):
        self._host = host
        self._port = port
        self._clients: Set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._search_callback: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None

    def set_search_callback(self, callback: Callable[[str, object], None]) -> None:
        self._search_callback = callback

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        import websockets
        async with websockets.serve(self._handler, self._host, self._port, ping_interval=20):
            print(f"[WS] Listening on ws://{self._host}:{self._port}/ws")
            await asyncio.Future()

    async def _handler(self, ws) -> None:
        self._clients.add(ws)
        print(f"[WS] Client connected ({len(self._clients)} total)")
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                    if data.get("type") == "search" and self._search_callback:
                        query = data.get("query", "").strip().lower()
                        if query:
                            self._search_callback(query, ws)
                except Exception as e:
                    print(f"[WS] Message parse error: {e}")
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            print(f"[WS] Client disconnected ({len(self._clients)} remaining)")

    def broadcast(self, message: dict) -> None:
        if not self._loop or not self._clients:
            return
        asyncio.run_coroutine_threadsafe(
            self._async_broadcast(json.dumps(message)), self._loop
        )

    def send_to(self, ws, message: dict) -> None:
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(
            self._async_send(ws, json.dumps(message)), self._loop
        )

    async def _async_broadcast(self, text: str) -> None:
        clients = list(self._clients)
        if clients:
            await asyncio.gather(*[c.send(text) for c in clients], return_exceptions=True)

    async def _async_send(self, ws, text: str) -> None:
        try:
            await ws.send(text)
        except Exception:
            pass
