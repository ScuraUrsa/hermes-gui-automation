"""Global desktop recorder for Windows and Linux/X11.

Captures mouse buttons, scrolling and keys system-wide with pynput (low-level
hooks on Windows, the X RECORD extension on X11), plus the active window and,
where the accessibility API answers, the element under the cursor or with
keyboard focus. Output is JSONL (``hermes_teach.events``).

Control keys (not recorded as steps):
  Ctrl+Shift+F12  stop recording
  Ctrl+Shift+F11  toggle privacy mode (keystrokes are masked, e.g. while you
                  type something that should never be stored)

Characters typed into a password field (UI Automation ``IsPassword`` on
Windows, AT-SPI ``password text`` on Linux) are never written to disk: they
are stored as a masked, ``sensitive`` event and become a Bitwarden reference
when the procedure is generalized.

Event callbacks only timestamp and enqueue; window/element lookups run on a
worker thread, because Windows silently drops low-level hooks that take too
long to return.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from hermes_teach import platform as plat_mod
from hermes_teach.events import (
    KEY_DOWN,
    KEY_UP,
    MARK,
    MOUSE_DOWN,
    MOUSE_UP,
    SCROLL,
    WINDOW,
    RawEvent,
    Target,
)

STOP_COMBO = frozenset({"ctrl", "shift", "f12"})
PRIVACY_COMBO = frozenset({"ctrl", "shift", "f11"})
_SIDES = {"ctrl_l": "ctrl", "ctrl_r": "ctrl", "alt_l": "alt", "alt_r": "alt", "shift_l": "shift",
          "shift_r": "shift", "shift": "shift", "cmd_l": "cmd", "cmd_r": "cmd", "cmd": "cmd",
          "ctrl": "ctrl", "alt": "alt"}


def canonical_key(key: Any) -> tuple[str, str | None]:
    """pynput key -> (canonical name, character or None)."""
    name = getattr(key, "name", None)
    if name:                                   # pynput.keyboard.Key member
        if name == "space":
            return "space", " "
        return _SIDES.get(name, name), None
    ch = getattr(key, "char", None)
    vk = getattr(key, "vk", None)
    if ch is not None and len(ch) == 1 and ord(ch) < 32 and ch not in "\t\r\n":
        ch = chr(ord(ch) + 96)                 # Windows reports Ctrl+S as '\x13'
    if ch is None and vk is not None:
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            ch = chr(vk).lower()
        else:
            return f"vk_{vk}", None
    return (ch.lower() if ch else ""), ch


class DesktopRecorder:
    def __init__(self, out_path: str | Path, *, screenshots_dir: str | Path | None = None,
                 window_poll: float = 0.5, on_event: Callable[[RawEvent], None] | None = None) -> None:
        self.out_path = Path(out_path)
        self.screenshots_dir = Path(screenshots_dir) if screenshots_dir else None
        self.window_poll = window_poll
        self.on_event = on_event
        self.plat = plat_mod.current()
        self._q: queue.Queue[tuple[float, str, dict[str, Any]] | None] = queue.Queue()
        self._held: set[str] = set()
        self._privacy = False
        self._t0 = 0.0
        self._stopped = threading.Event()
        self._listeners: list[Any] = []
        self._worker: threading.Thread | None = None
        self._last_window: dict[str, Any] = {}
        self._last_window_t = 0.0
        self._focus_cache: tuple[float, dict[str, Any]] = (0.0, {})
        self.count = 0

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> "DesktopRecorder":
        from pynput import keyboard, mouse

        self._t0 = time.monotonic()
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.screenshots_dir:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self._worker = threading.Thread(target=self._work, name="hermes-teach-recorder", daemon=True)
        self._worker.start()
        self._enqueue(MARK, {"mark": "start", "platform": os.name})
        self._listeners = [
            mouse.Listener(on_click=self._on_click, on_scroll=self._on_scroll),
            keyboard.Listener(on_press=self._on_press, on_release=self._on_release),
        ]
        for lst in self._listeners:
            lst.start()
        for lst in self._listeners:
            lst.wait()
        return self

    def stop(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        for lst in self._listeners:
            lst.stop()
        self._enqueue(MARK, {"mark": "stop"})
        self._q.put(None)
        if self._worker is not None:
            self._worker.join(timeout=10)
        self._fh.close()

    def wait(self, timeout: float | None = None) -> bool:
        return self._stopped.wait(timeout)

    def __enter__(self) -> "DesktopRecorder":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # --- hook callbacks (keep them tiny) ----------------------------------
    def _enqueue(self, kind: str, data: dict[str, Any]) -> None:
        self._q.put((time.monotonic() - self._t0, kind, data))

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        self._enqueue(MOUSE_DOWN if pressed else MOUSE_UP,
                      {"x": int(x), "y": int(y), "button": getattr(button, "name", str(button))})

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._enqueue(SCROLL, {"x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def _on_press(self, key: Any) -> None:
        name, ch = canonical_key(key)
        if name in ("ctrl", "shift", "alt", "cmd"):
            self._held.add(name)
        combo = self._held | {name}
        if combo >= STOP_COMBO and name == "f12":
            threading.Thread(target=self.stop, daemon=True).start()
            return
        if combo >= PRIVACY_COMBO and name == "f11":
            self._privacy = not self._privacy
            self._enqueue(MARK, {"mark": "privacy_on" if self._privacy else "privacy_off"})
            return
        self._enqueue(KEY_DOWN, {"key": name, "char": ch, "privacy": self._privacy})

    def _on_release(self, key: Any) -> None:
        name, _ = canonical_key(key)
        self._held.discard(name)
        self._enqueue(KEY_UP, {"key": name})

    # --- worker: enrich and write ----------------------------------------
    def _window(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if force or now - self._last_window_t > 0.25:
            try:
                self._last_window = self.plat.active_window()
            except Exception:
                self._last_window = {}
            self._last_window_t = now
        return self._last_window

    def _focused(self) -> dict[str, Any]:
        now = time.monotonic()
        t, info = self._focus_cache
        if now - t > 0.5:
            try:
                info = self.plat.focused_element()
            except Exception:
                info = {}
            self._focus_cache = (now, info)
        return info

    def _target(self, win: dict[str, Any], x: int | None = None, y: int | None = None,
                elem: dict[str, Any] | None = None) -> Target:
        tgt = Target(x=x, y=y, window_title=win.get("title", ""), window_class=win.get("class", ""),
                     process=win.get("process", ""))
        rect = win.get("rect") or {}
        if x is not None and y is not None and "x" in rect:
            tgt.off_x, tgt.off_y = x - rect["x"], y - rect["y"]
        if elem:
            tgt.element_name = elem.get("name", "")
            tgt.element_role = elem.get("role", "")
            tgt.automation_id = elem.get("automation_id", "")
        return tgt

    def _write(self, ev: RawEvent) -> None:
        self._fh.write(ev.to_json() + "\n")
        self._fh.flush()
        self.count += 1
        if self.on_event is not None:
            self.on_event(ev)

    def _maybe_window_event(self, t: float, force: bool = False) -> None:
        prev = self._last_window.get("title")
        win = self._window(force=force)
        if win.get("title") and win.get("title") != prev:
            self._write(RawEvent(t=t, kind=WINDOW, target=self._target(win)))

    def _shot(self, x: int, y: int, t: float) -> str:
        if self.screenshots_dir is None:
            return ""
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                box = {"left": max(0, x - 80), "top": max(0, y - 80), "width": 160, "height": 160}
                img = sct.grab(box)
                name = f"click_{t:010.3f}.png"
                mss.tools.to_png(img.rgb, img.size, output=str(self.screenshots_dir / name))
                return name
        except Exception:
            return ""

    def _work(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=self.window_poll)
            except queue.Empty:
                if not self._stopped.is_set():
                    self._maybe_window_event(time.monotonic() - self._t0, force=True)
                continue
            if item is None:
                return
            t, kind, data = item
            if kind == MARK:
                self._write(RawEvent(t=t, kind=kind, data=data))
                continue
            self._maybe_window_event(t)
            win = self._last_window
            if kind in (MOUSE_DOWN, MOUSE_UP):
                x, y = data["x"], data["y"]
                elem = None
                if kind == MOUSE_DOWN:
                    try:
                        elem = self.plat.element_at(x, y)
                    except Exception:
                        elem = None
                    self._focus_cache = (0.0, {})   # focus probably moves with the click
                    shot = self._shot(x, y, t)
                    if shot:
                        data = {**data, "shot": shot}
                self._write(RawEvent(t=t, kind=kind, data={k: v for k, v in data.items() if k not in ("x", "y")},
                                     target=self._target(win, x, y, elem)))
            elif kind == SCROLL:
                self._write(RawEvent(t=t, kind=kind, data={"dx": data["dx"], "dy": data["dy"]},
                                     target=self._target(win, data["x"], data["y"])))
            elif kind == KEY_DOWN:
                focus = self._focused() if data.get("char") else {}
                sensitive = bool(data.get("privacy")) or bool(focus.get("is_password"))
                out = {"key": data["key"], "char": data.get("char")}
                if sensitive and out["char"]:
                    out = {"key": "masked", "char": "•", "sensitive": True}
                self._write(RawEvent(t=t, kind=kind, data=out, target=self._target(win, elem=focus)))
            elif kind == KEY_UP:
                self._write(RawEvent(t=t, kind=kind, data=data))
