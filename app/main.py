import asyncio
import json
import threading
from typing import Optional, Set

import websockets
import websockets.exceptions

_loop: Optional[asyncio.AbstractEventLoop] = None
_connected: Set = set()
_navigation_service = None


def set_navigation_service(service) -> None:
    global _navigation_service
    _navigation_service = service


async def _ws_handler(websocket) -> None:
    _connected.add(websocket)
    print(f"[WS] Client connected ({len(_connected)} total)")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "search" and _navigation_service is not None:
                    result = _navigation_service.search(data.get("query", ""))
                    await websocket.send(json.dumps(result))
            except Exception as e:
                print(f"[WS] Message error: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _connected.discard(websocket)
        print(f"[WS] Client disconnected ({len(_connected)} total)")


async def _broadcast_all(message: str) -> None:
    if not _connected:
        return
    await asyncio.gather(
        *[c.send(message) for c in list(_connected)],
        return_exceptions=True,
    )


async def _serve() -> None:
    print("[WS] Server starting on ws://0.0.0.0:8001")
    async with websockets.serve(_ws_handler, "0.0.0.0", 8001):
        await asyncio.Future()  # run forever


def _run_server() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_serve())


def start_in_background() -> None:
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()


def broadcast(message: dict) -> None:
    if _loop is None or not _connected:
        return
    asyncio.run_coroutine_threadsafe(_broadcast_all(json.dumps(message)), _loop)
