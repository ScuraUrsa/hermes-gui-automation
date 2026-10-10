"""Desktop driver for Windows and Linux/X11.

Synthetic input goes through pynput (SendInput on Windows, XTEST on X11), so
the same code drives both systems. Targets are resolved in order of
robustness:

1. accessible element (UI Automation / AT-SPI) by AutomationId or name+role
   inside the target window,
2. pixel offset from the target window's top-left corner (survives the window
   being moved),
3. the absolute coordinates from the recording.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from typing import Any

from hermes_teach import platform as plat_mod
from hermes_teach.drivers.base import DriverError
from hermes_teach.events import Target


def _pynput():  # type: ignore[no-untyped-def]
    try:
        from pynput import keyboard, mouse
    except Exception as e:  # pragma: no cover - depends on display
        raise DriverError(f"pynput unavailable (no display?): {e}") from None
    return keyboard, mouse


class DesktopDriver:
    def __init__(self, action_delay: float = 0.15, type_interval: float = 0.0) -> None:
        self.plat = plat_mod.current()
        keyboard, mouse = _pynput()
        self._kb_mod, self._mouse_mod = keyboard, mouse
        self.kb = keyboard.Controller()
        self.mouse = mouse.Controller()
        self.action_delay = action_delay
        self.type_interval = type_interval
        self._handle: Any = None
        self._handle_title = ""

    # --- target resolution -------------------------------------------------
    def _window_for(self, target: Target) -> Any:
        if not target.window_title:
            return self._handle
        if self._handle is not None and plat_mod.title_matches(target.window_title, self._handle_title):
            return self._handle
        for w in self.plat.list_windows():
            if plat_mod.title_matches(target.window_title, w["title"]):
                return w["handle"]
        return self._handle

    def resolve(self, target: Target) -> tuple[int, int]:
        handle = self._window_for(target)
        if handle is not None and (target.automation_id or target.element_name):
            pt = self.plat.find_element(handle, target.element_name, target.element_role,
                                        target.automation_id)
            if pt is not None:
                return pt
        if handle is not None and target.off_x is not None and target.off_y is not None:
            rect = self.plat.window_rect(handle)
            if rect:
                return rect["x"] + int(target.off_x), rect["y"] + int(target.off_y)
        if target.x is None or target.y is None:
            raise DriverError(f"cannot locate {target.describe()}")
        return int(target.x), int(target.y)

    # --- actions -----------------------------------------------------------
    def _button(self, name: str) -> Any:
        return getattr(self._mouse_mod.Button, name, self._mouse_mod.Button.left)

    def click(self, target: Target, button: str = "left", count: int = 1) -> None:
        x, y = self.resolve(target)
        self.mouse.position = (x, y)
        time.sleep(0.05)
        self.mouse.click(self._button(button), count)
        time.sleep(self.action_delay)

    def type_text(self, text: str, target: Target | None = None) -> None:
        if self.type_interval <= 0:
            self.kb.type(text)
        else:
            for ch in text:
                self.kb.type(ch)
                time.sleep(self.type_interval)
        time.sleep(self.action_delay)

    def _key(self, name: str) -> Any:
        Key = self._kb_mod.Key
        alias = {"return": "enter", "escape": "esc", "del": "delete", "pgup": "page_up",
                 "pgdn": "page_down", "win": "cmd", "super": "cmd", "control": "ctrl"}
        n = alias.get(name.lower(), name.lower())
        if hasattr(Key, n):
            return getattr(Key, n)
        if len(name) == 1:
            return self._kb_mod.KeyCode.from_char(name)
        raise DriverError(f"unknown key '{name}'")

    def press(self, keys: list[str]) -> None:
        objs = [self._key(k) for k in keys]
        for k in objs:
            self.kb.press(k)
        for k in reversed(objs):
            self.kb.release(k)
        time.sleep(self.action_delay)

    def scroll(self, target: Target, dx: int, dy: int) -> None:
        if target.x is not None or target.off_x is not None or target.element_name:
            self.mouse.position = self.resolve(target)
        self.mouse.scroll(dx, dy)
        time.sleep(self.action_delay)

    def drag(self, target: Target, dx: int, dy: int, button: str = "left") -> None:
        x, y = self.resolve(target)
        self.mouse.position = (x, y)
        self.mouse.press(self._button(button))
        steps = 10
        for i in range(1, steps + 1):
            self.mouse.position = (x + dx * i // steps, y + dy * i // steps)
            time.sleep(0.02)
        self.mouse.release(self._button(button))
        time.sleep(self.action_delay)

    def focus(self, target: Target, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while True:
            for w in self.plat.list_windows():
                if plat_mod.title_matches(target.window_title, w["title"]):
                    self.plat.activate(w["handle"])
                    self._handle, self._handle_title = w["handle"], w["title"]
                    time.sleep(self.action_delay)
                    return
            if time.time() > deadline:
                raise DriverError(f"window '{target.window_title}' not found")
            time.sleep(0.25)

    def launch(self, command: str) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(command, shell=True)  # noqa: S602 - command comes from a reviewed procedure
        else:
            subprocess.Popen(shlex.split(command), start_new_session=True)
        time.sleep(self.action_delay)

    def active_window_title(self) -> str:
        return str(self.plat.active_window().get("title", ""))

    def close(self) -> None:
        return None
