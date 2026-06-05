"""
sbs.py — Remote GUI API implementation.

All send_gui_* calls serialize a command dict and put it onto
`gui_queue` (a queue.Queue).  The web server drains that queue
and forwards every command to the appropriate browser client via
WebSocket.

Usage (script engine side):
    from sbs import gui_queue, send_gui_clear, send_gui_button, ...
    # gui_queue is passed to / shared with the web server process/thread
"""

import json
import multiprocessing
from typing import Any

# ---------------------------------------------------------------------------
# Shared queues  (set to multiprocessing.Queue instances by start_server)
# ---------------------------------------------------------------------------
# Outbound GUI commands — script engine writes, server reads.
gui_queue: multiprocessing.Queue = None  # type: ignore[assignment]

# Inbound connection lifecycle events from the server to the script engine.
# {"event": "connect"|"disconnect", "clientID": int}
client_event_queue: multiprocessing.Queue = None  # type: ignore[assignment]

# Inbound widget events from the browser to the script engine.
# {"type": "click"|"change"|..., "tag": str, "clientID": int, ...}
gui_event_queue: multiprocessing.Queue = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Server launcher — runs the server in a separate process.
# Queues are created here, injected into sbs on the parent side, and passed
# as arguments to the child so both sides share the same OS-level pipes.
# ---------------------------------------------------------------------------
def start_server(host: str = "0.0.0.0", port: int = 8765) -> multiprocessing.Process:
    """Start the WebSocket bridge server in a child process.

    Creates multiprocessing.Queue instances for all three queues, assigns
    them to this module so send_gui_* calls work immediately, then spawns
    the server process and waits until it is ready to accept connections.
    Returns the Process object.
    """
    global gui_queue, client_event_queue, gui_event_queue

    gui_queue          = multiprocessing.Queue()
    client_event_queue = multiprocessing.Queue()
    gui_event_queue    = multiprocessing.Queue()
    ready              = multiprocessing.Event()

    from server import run_server  # lazy import to avoid circular dependency
    p = multiprocessing.Process(
        target=run_server,
        args=(gui_queue, client_event_queue, gui_event_queue, ready, host, port),
        daemon=True,
        name="sbs-server",
    )
    p.start()

    if not ready.wait(timeout=10):
        p.terminate()
        raise RuntimeError(f"sbs server did not start within 10 s on {host}:{port}")
    return p


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------
def _send(clientID: int, cmd: str, **kwargs: Any) -> None:
    """Serialise a command and enqueue it."""
    payload = {"clientID": clientID, "cmd": cmd, **kwargs}
    gui_queue.put(payload)


# ---------------------------------------------------------------------------
# Buffer control
# ---------------------------------------------------------------------------
def send_gui_clear(clientID: int, tag: str) -> None:
    """Clears all GUI elements from screen on the targeted client."""
    _send(clientID, "clear", tag=tag)


def send_gui_complete(clientID: int, tag: str) -> None:
    """Flips the double-buffered display list on the targeted client."""
    _send(clientID, "complete", tag=tag)


# ---------------------------------------------------------------------------
# Widget helpers – all positional widgets share the same shape
# ---------------------------------------------------------------------------
def _widget(cmd: str, clientID: int, parent: str, tag: str,
             style: str, left: float, top: float,
             right: float, bottom: float) -> None:
    _send(clientID, cmd,
          parent=parent, tag=tag, style=style,
          left=left, top=top, right=right, bottom=bottom)


def send_gui_button(clientID, parent, tag, style, left, top, right, bottom):
    _widget("button", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_checkbox(clientID, parent, tag, style, left, top, right, bottom):
    _widget("checkbox", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_clickregion(clientID, parent, tag, style, left, top, right, bottom):
    _widget("clickregion", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_colorbutton(clientID, parent, tag, style, left, top, right, bottom):
    _widget("colorbutton", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_colorcheckbox(clientID, parent, tag, style, left, top, right, bottom):
    _widget("colorcheckbox", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_dropdown(clientID, parent, tag, style, left, top, right, bottom):
    _widget("dropdown", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_icon(clientID, parent, tag, style, left, top, right, bottom):
    _widget("icon", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_iconbutton(clientID, parent, tag, style, left, top, right, bottom):
    _widget("iconbutton", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_iconcheckbox(clientID, parent, tag, style, left, top, right, bottom):
    _widget("iconcheckbox", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_image(clientID, parent, tag, style, left, top, right, bottom):
    _widget("image", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_rawiconbutton(clientID, parent, tag, style, left, top, right, bottom):
    _widget("rawiconbutton", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_sub_region(clientID, parent, tag, style, left, top, right, bottom):
    _widget("sub_region", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_text(clientID, parent, tag, style, left, top, right, bottom):
    _widget("text", clientID, parent, tag, style, left, top, right, bottom)


def send_gui_typein(clientID, parent, tag, style, left, top, right, bottom):
    _widget("typein", clientID, parent, tag, style, left, top, right, bottom)


# ---------------------------------------------------------------------------
# Widgets with extra parameters
# ---------------------------------------------------------------------------
def send_gui_face(clientID: int, parent: str, tag: str, face_string: str,
                  left: float, top: float, right: float, bottom: float) -> None:
    _send(clientID, "face",
          parent=parent, tag=tag, face_string=face_string,
          left=left, top=top, right=right, bottom=bottom)


def send_gui_slider(clientID: int, parent: str, tag: str, current: float,
                    style: str, left: float, top: float,
                    right: float, bottom: float) -> None:
    _send(clientID, "slider",
          parent=parent, tag=tag, current=current, style=style,
          left=left, top=top, right=right, bottom=bottom)


def send_gui_hotkey(clientID: int, category: str, tag: str,
                    keyType: str, description: str) -> None:
    _send(clientID, "hotkey",
          category=category, tag=tag,
          keyType=keyType, description=description)
