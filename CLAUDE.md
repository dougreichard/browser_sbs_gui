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
| `style` | str | Style string: `key:value;key:value` — see Style String Format below |
| `left/top/right/bottom` | float | Root-relative 0–100 bounding box |

### Standard widgets

```python
send_gui_button(clientID, parent, tag, style, left, top, right, bottom)
send_gui_checkbox(clientID, parent, tag, style, left, top, right, bottom)
send_gui_clickregion(clientID, parent, tag, style, left, top, right, bottom)
send_gui_colorbutton(clientID, parent, tag, style, left, top, right, bottom)
send_gui_colorcheckbox(clientID, parent, tag, style, left, top, right, bottom)
send_gui_dropdown(clientID, parent, tag, style, left, top, right, bottom)
send_gui_icon(clientID, parent, tag, style, left, top, right, bottom)
send_gui_iconbutton(clientID, parent, tag, style, left, top, right, bottom)
send_gui_iconcheckbox(clientID, parent, tag, style, left, top, right, bottom)
send_gui_image(clientID, parent, tag, style, left, top, right, bottom)
send_gui_rawiconbutton(clientID, parent, tag, style, left, top, right, bottom)
send_gui_sub_region(clientID, parent, tag, style, left, top, right, bottom)
send_gui_text(clientID, parent, tag, style, left, top, right, bottom)
send_gui_typein(clientID, parent, tag, style, left, top, right, bottom)
```

### Widgets with non-standard parameters

```python
send_gui_face(clientID, parent, tag, face_string, left, top, right, bottom)
    # face_string = emoji or face content (not a style string)

send_gui_slider(clientID, parent, tag, current, style, left, top, right, bottom)
    # current = initial value (float); style string carries low/high/etc.

send_gui_hotkey(clientID, category, tag, keyType, description)
    # keyType = JS KeyboardEvent.key or .code string e.g. "F5", "Enter"
    # No visual widget; registers a keyboard shortcut in the browser
```

---

## Style String Format

The `style` parameter is a structured string of `key:value` pairs separated by
semicolons:

```
key:value;key:value;key:value
```

**Parsing rules:**
- Pairs are separated by `;`.
- Key and value are separated by the **first** `:` in the pair — values may
  contain colons freely (e.g. `color:#ef4444` works without escaping).
- The `text` key's value may optionally be enclosed in backticks to protect
  semicolons or colons inside the text: `` text:`Hello; World` `` → `Hello; World`.
- Boolean flags (`state`, `visible`, `pixel_aligned`, `password`, etc.) are
  truthy when the value is `on`, `yes`, `True`, or `active` (case-insensitive).
  `show_number` on `slider` is a hide flag — falsy values (`no`, `False`) hide
  the number.

### Common keys (most widgets)

| Key | Type | Description |
|-----|------|-------------|
| `text` | str | Display text; backtick-enclose to include `;` or `:` |
| `color` | CSS color | Text color (or button/swatch color for colorbutton/colorcheckbox) |
| `font` | str | Font tag from preferences.json |
| `draw_layer` | int | CSS z-index; default 1001 |
| `pixel_aligned` | flag | Use px instead of % for positioning |

### Widget-specific keys

| Widget | Key | Description |
|--------|-----|-------------|
| `checkbox` | `state` | Initial checked state (flag) |
| `checkbox` | `visible` | Initial visibility (flag) |
| `clickregion` | `background_color` | Background fill color for the region |
| `dropdown` | `list` | Comma-separated option list, e.g. `Normal,Debug,Verbose` |
| `icon`, `iconbutton`, `iconcheckbox`, `rawiconbutton` | `icon_index` | Integer index into `grid-icon-sheet.png` sprite sheet |
| `image` | `image` | Filename without `.png` suffix; path relative to `data/graphics/` |
| `image` | `sub_rect` | Four comma-separated 0–1 floats: `left,top,right,bottom` of source image |
| `image` | `sub_left/top/right/bottom` | Individual sub-rect edges (alternative to `sub_rect`) |
| `slider` | `low` | Minimum value (float) |
| `slider` | `high` | Maximum value (float) |
| `slider` | `show_number` | Hide the numeric readout when `no` or `False` |
| `text` | `justify` | Text alignment: `left`, `right`, or `center` |
| `typein` | `desc` | Placeholder text |
| `typein` | `password` | Mask input as asterisks (flag) |

### Examples

```python
send_gui_button(cid, "", "btn_ok", "text:OK;color:#22c55e", 40, 45, 60, 55)

send_gui_text(cid, "", "lbl", "text:`Name:`;justify:right", 2, 3, 48, 11)

send_gui_slider(cid, "", "vol", 65.0, "low:0;high:100", 2, 35, 98, 45)

send_gui_dropdown(cid, "", "dd", "list:Normal,Debug,Verbose", 2, 70, 98, 80)

send_gui_image(cid, "", "img", "image:hud/panel;sub_rect:0,0,0.5,1", 0, 0, 50, 100)

send_gui_typein(cid, "", "inp", "desc:Enter name…;password:no", 2, 13, 98, 23)
```

---

## Browser Events

When the user interacts with a widget the browser sends a JSON message back
over the same WebSocket.

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

Events are delivered to the script engine via `sbs.gui_event_queue`
(a `multiprocessing.Queue` populated by `server.py`).

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
- `clientID > 0` — commands are sent only to the browser assigned that ID.
- `clientID == 0` — commands are broadcast to **all** connected browsers and
  the frame is also replayed to every future client regardless of their own ID.

### Coordinate system (important)
All `left/top/right/bottom` values are root-canvas-relative even when a
`parent` tag is specified. The `parent` parameter is a **logical tag** used for
grouping and hotkey categories — it does not create a CSS containing block or
change the coordinate origin.

---

## Known Limitations / TODO

- `icon_index` references `grid-icon-sheet.png` which is not bundled; the browser
  displays `[N]` as a placeholder instead of the sprite.
- `send_gui_image` sub-rect is implemented via CSS `background-size`/`background-position`
  math; images must be served from the same origin or have permissive CORS headers.
- Hotkeys registered via `send_gui_hotkey` accumulate across frames (no deregistration
  on `clear`); avoid registering the same key repeatedly.
- The server does not authenticate WebSocket connections; run behind a firewall or
  add token auth for production use.
- `send_gui_dropdown` option values must not contain commas (the `list` value is
  split on commas; no alternate delimiter is supported).
