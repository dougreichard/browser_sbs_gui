# SBS Remote GUI — CLAUDE.md

## Project Overview

This project implements a **remote GUI system** where a Python script engine
draws UI screens that appear in a browser. The three-layer pipeline is:

```
Script engine (your code)
  └─ calls sbs.send_gui_*()
       └─ puts JSON commands onto gui_queue (queue.Queue)
            └─ server.py drains the queue via asyncio
                 └─ forwards commands over WebSocket to browser(s)
                      └─ client.html renders widgets as DOM elements
```

---

## Files

| File | Role |
|------|------|
| `sbs.py` | Public API — all `send_gui_*` functions + shared `gui_queue` |
| `server.py` | FastAPI WebSocket bridge; serves `client.html`; replays last frame on connect |
| `client.html` | Browser renderer; double-buffered DOM widget system |
| `demo.py` | Example script engine showing all widget types |

---

## Running

```bash
pip install fastapi uvicorn websockets

# Terminal 1 — bridge server (must be running first)
python server.py

# Terminal 2 — your script engine
python demo.py

# Browser (open as many tabs as you like — each gets a unique ID from the server)
open http://localhost:8765/
```

Each browser tab is assigned a `clientID` automatically by the server when it
connects. The assigned ID is displayed in the top bar. Use that ID in
`send_gui_*` calls to target that tab.
Use `clientID=0` to broadcast to all connected browsers simultaneously.

---

## API Reference (`sbs.py`)

### Buffer control

Every screen update must be wrapped in a clear/complete pair. The browser uses
double-buffering: widgets are built in a hidden back-buffer and swapped visible
atomically on `send_gui_complete`.

```python
send_gui_clear(clientID, tag)     # wipe back-buffer, start new frame
# ... add widgets ...
send_gui_complete(clientID, tag)  # swap back-buffer → front (visible)
```

### Coordinate system

All positional arguments (`left`, `top`, `right`, `bottom`) are **numbers
in the range 0–100** (percentages).

- **Root widgets** (`parent=""`): coordinates are percentages of the browser
  viewport, where `(0,0)` is the top-left corner and `(100,100)` is the
  bottom-right corner.
- **Child widgets** (`parent=<sub_region tag>`): coordinates are percentages
  of the named `send_gui_sub_region`'s bounding box. `(0,0)` is the
  sub_region's top-left and `(100,100)` is its bottom-right.

```python
# A button in the centre of the screen (root coords)
send_gui_button(clientID, parent="", tag="btn_ok", style="OK",
                left=40, top=45, right=60, bottom=55)

# A button filling the top-right quarter of a sub_region called "panel"
send_gui_button(clientID, parent="panel", tag="btn_ok", style="OK",
                left=50, top=0, right=100, bottom=50)
```

### Widget signatures

All standard widgets share the same positional signature:

```python
send_gui_*(clientID, parent, tag, style, left, top, right, bottom)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `clientID` | int | Target browser (0 = all) |
| `parent` | str | Logical grouping tag (visual-only; does not affect coordinate origin) |
| `tag` | str | Unique identifier for this widget; returned in browser events |
| `style` | str | Widget-specific: label text, CSS colour, comma-separated options, icon glyph, image URL, etc. |
| `left/top/right/bottom` | float | Root-relative 0–1 bounding box |

### Standard widgets

```python
send_gui_button(clientID, parent, tag, style, left, top, right, bottom)
send_gui_checkbox(clientID, parent, tag, style, left, top, right, bottom)
send_gui_clickregion(clientID, parent, tag, style, left, top, right, bottom)
send_gui_colorbutton(clientID, parent, tag, style, left, top, right, bottom)
    # style = CSS colour string e.g. "#ef4444"
send_gui_colorcheckbox(clientID, parent, tag, style, left, top, right, bottom)
    # style = CSS colour string
send_gui_dropdown(clientID, parent, tag, style, left, top, right, bottom)
    # style = comma-separated option list e.g. "Normal,Debug,Verbose"
send_gui_icon(clientID, parent, tag, style, left, top, right, bottom)
    # style = emoji or unicode glyph
send_gui_iconbutton(clientID, parent, tag, style, left, top, right, bottom)
send_gui_iconcheckbox(clientID, parent, tag, style, left, top, right, bottom)
send_gui_image(clientID, parent, tag, style, left, top, right, bottom)
    # style = image URL
send_gui_rawiconbutton(clientID, parent, tag, style, left, top, right, bottom)
send_gui_sub_region(clientID, parent, tag, style, left, top, right, bottom)
    # visual panel/grouping box; children still use root coords
send_gui_text(clientID, parent, tag, style, left, top, right, bottom)
    # style = display text
send_gui_typein(clientID, parent, tag, style, left, top, right, bottom)
    # style = placeholder text
```

### Widgets with non-standard parameters

```python
send_gui_face(clientID, parent, tag, face_string, left, top, right, bottom)
    # face_string = emoji or face content

send_gui_slider(clientID, parent, tag, current, style, left, top, right, bottom)
    # current = initial value (0–100)

send_gui_hotkey(clientID, category, tag, keyType, description)
    # keyType = JS KeyboardEvent.key or .code string e.g. "F5", "Enter"
    # No visual widget; registers a keyboard shortcut in the browser
```

---

## Browser Events

When the user interacts with a widget the browser sends a JSON message back
over the same WebSocket. The server currently prints these; wire them to a
second `queue.Queue` in `server.py` to consume them in your script engine.

| Event type | Widgets | Extra fields |
|------------|---------|--------------|
| `click` | button, clickregion, colorbutton, iconbutton, rawiconbutton | `color` (colorbutton only) |
| `change` | checkbox, colorcheckbox, dropdown, iconcheckbox, slider, typein | `checked`, `value`, `color` (type-dependent) |
| `submit` | typein | `value` |
| `hotkey` | hotkey | `keyType`, `category` |

Example event payload received by the server:
```json
{ "type": "click", "tag": "btn_ok", "clientID": 1 }
{ "type": "change", "tag": "sld_volume", "value": 72.0, "clientID": 1 }
```

---

## Architecture Notes

### Double-buffering
The browser maintains two invisible `<div>` layers (`buf-front`, `buf-back`).
`send_gui_clear` wipes the back layer. Each `send_gui_*` widget call appends a
DOM element to the back layer. `send_gui_complete` atomically makes the back
layer visible and demotes the old front layer. This eliminates flicker during
screen rebuilds.

### Frame replay
`server.py` records every committed frame (`clear` … `complete`) in
`_last_frame[clientID]`. When a new browser connects, the server immediately
replays the last frame so late-joining or refreshed clients always see the
current screen without needing the script engine to redraw.

### clientID routing
- `clientID > 0` — commands are sent only to browsers connected at
  `ws://host/ws/<clientID>`.
- `clientID == 0` — commands are broadcast to **all** connected browsers and
  the frame is also replayed to every future client regardless of their own ID.

### Coordinate system (important)
All `left/top/right/bottom` values are root-canvas-relative even when a
`parent` tag is specified. The `parent` parameter is a **logical tag** used for
grouping and hotkey categories — it does not create a CSS containing block or
change the coordinate origin.

---

## Adding Browser Event Consumption

To receive widget events in your script engine, add an event queue to
`server.py`:

```python
# server.py addition
import sbs
gui_event_queue: queue.Queue = queue.Queue()   # export alongside gui_queue

# inside websocket_endpoint, replace the print:
gui_event_queue.put(event)
```

Then in your script engine:
```python
from server import gui_event_queue   # or pass the queue at startup

event = gui_event_queue.get()        # blocks until an event arrives
print(event["type"], event["tag"])
```

---

## Known Limitations / TODO

- `send_gui_slider` min/max are currently hardcoded to 0–100 in the browser; the `style` parameter could encode `"min,max"` to override.
- `send_gui_dropdown` option list is carried in `style` as a comma-separated string; values containing commas must be avoided or a different delimiter used.
- `send_gui_image` loads images by URL; base64 data-URIs work but must be set in `style`.
- Hotkeys registered via `send_gui_hotkey` accumulate across frames (no deregistration on `clear`); avoid registering the same key repeatedly.
- The server does not authenticate WebSocket connections; run behind a firewall or add token auth for production use.