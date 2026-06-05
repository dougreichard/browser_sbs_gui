"""
server.py — WebSocket bridge between the script engine (sbs.py Queue)
            and browser GUI clients.

Install deps:
    pip install fastapi uvicorn websockets

Run:
    python server.py

Each browser client connects to  ws://localhost:8765/ws/<clientID>
clientID == 0  →  "server screen" (broadcast to all connected clients)
clientID >  0  →  targeted client only

On connect, the server immediately replays the last recorded frame for that
clientID so late-joining browsers always see the current screen.
"""

import asyncio
import json
import multiprocessing
import os
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

import sbs  # shares gui_queue

# Set by run_server() before uvicorn starts; signalled from the lifespan.
_ready_event: Optional[multiprocessing.Event] = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE        = os.path.dirname(os.path.abspath(__file__))
_CLIENT_HTML = os.path.join(_HERE, "client.html")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
# clientID → active WebSocket connections
_connections: Dict[int, Set[WebSocket]] = {}

# Auto-incrementing counter for assigning clientIDs
_next_client_id: int = 1

# clientID → ordered list of commands in the last complete frame
# A "frame" is everything between send_gui_clear … send_gui_complete (inclusive).
# When a new browser connects it receives this list so it can reconstruct the screen.
_last_frame:    Dict[int, List[dict]] = {}   # last committed (complete) frame
_pending_frame: Dict[int, List[dict]] = {}   # frame being built (after clear, before complete)

_lock: asyncio.Lock | None = None

def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
async def _register(client_id: int, ws: WebSocket) -> None:
    async with _get_lock():
        _connections.setdefault(client_id, set()).add(ws)


async def _unregister(client_id: int, ws: WebSocket) -> None:
    async with _get_lock():
        _connections.get(client_id, set()).discard(ws)


async def _replay(client_id: int, ws: WebSocket) -> None:
    """Send the last committed frame to a freshly connected client."""
    frames_to_replay: List[dict] = []
    async with _get_lock():
        frames_to_replay = list(_last_frame.get(0, [])) + list(_last_frame.get(client_id, []))

    print(f"[replay] client={client_id} sending {len(frames_to_replay)} commands "
          f"(last_frame keys={list(_last_frame.keys())})")

    for payload in frames_to_replay:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception as e:
            print(f"[replay] send failed: {e}")
            break

    print(f"[replay] client={client_id} done")

# ---------------------------------------------------------------------------
# Broadcast + frame recording
# ---------------------------------------------------------------------------
async def _broadcast(payload: dict) -> None:
    """Record the command into the pending frame and forward to live clients."""
    client_id = payload.get("clientID", 0)
    cmd       = payload.get("cmd")

    async with _get_lock():
        if cmd == "clear":
            # Start a new pending frame, discarding any uncommitted leftovers
            _pending_frame[client_id] = [payload]
        elif cmd == "complete":
            # Commit the pending frame (append the complete sentinel, then promote)
            frame = _pending_frame.get(client_id, [])
            frame.append(payload)
            _last_frame[client_id]   = frame
            _pending_frame[client_id] = []
        else:
            # Widget command — accumulate into the pending frame
            _pending_frame.setdefault(client_id, []).append(payload)

        # Resolve live targets
        if client_id == 0:
            targets: Set[WebSocket] = set()
            for bucket in _connections.values():
                targets |= bucket
        else:
            targets = set(_connections.get(client_id, set()))

    # Send to all live targets (outside the lock)
    dead = []
    msg  = json.dumps(payload)
    for ws in targets:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)

    if dead:
        async with _get_lock():
            for ws in dead:
                for bucket in _connections.values():
                    bucket.discard(ws)


# ---------------------------------------------------------------------------
# Queue dispatcher
# ---------------------------------------------------------------------------
async def _queue_dispatcher() -> None:
    loop = asyncio.get_event_loop()
    while True:
        payload = await loop.run_in_executor(None, sbs.gui_queue.get)
        await _broadcast(payload)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_queue_dispatcher())
    if _ready_event is not None:
        _ready_event.set()   # unblock start_server() in the parent process
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="SBS GUI Bridge", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open(_CLIENT_HTML, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(
            content=f"<pre>client.html not found at:\n{_CLIENT_HTML}</pre>",
            status_code=500,
        )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _next_client_id
    await websocket.accept()

    # Assign a unique clientID and tell the client what it is
    async with _get_lock():
        client_id = _next_client_id
        _next_client_id += 1
    await websocket.send_text(json.dumps({"cmd": "init", "clientID": client_id}))

    await _register(client_id, websocket)
    sbs.client_event_queue.put({"event": "connect", "clientID": client_id})
    print(f"[server] client {client_id} connected")

    # Immediately paint the current screen for this client
    await _replay(client_id, websocket)

    try:
        while True:
            data  = await websocket.receive_text()
            event = json.loads(data)
            event["clientID"] = client_id
            print(f"[event]  client={client_id} {event}")
            sbs.gui_event_queue.put(event)
    except WebSocketDisconnect:
        print(f"[server] client {client_id} disconnected")
    finally:
        await _unregister(client_id, websocket)
        sbs.client_event_queue.put({"event": "disconnect", "clientID": client_id})


# ---------------------------------------------------------------------------
# Subprocess entry point (called by sbs.start_server)
# ---------------------------------------------------------------------------
def run_server(
    gui_q: multiprocessing.Queue,
    client_event_q: multiprocessing.Queue,
    gui_event_q: multiprocessing.Queue,
    ready_event: multiprocessing.Event,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> None:
    """Inject shared queues, then start uvicorn.  Runs in a child process."""
    global _ready_event
    sbs.gui_queue          = gui_q
    sbs.client_event_queue = client_event_q
    sbs.gui_event_queue    = gui_event_q
    _ready_event           = ready_event
    uvicorn.run(app, host=host, port=port, log_level="info")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False)
