"""Windows context via Win32 (ctypes) and, if installed, UI Automation.

``pip install uiautomation`` enables element names/roles/AutomationIds and
password-field detection; without it the recorder still captures window
title, process and coordinates relative to the window.
"""

from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes
from typing import Any

user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

try:  # same coordinate space as pynput / SendInput on scaled displays
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def window_rect(handle: Any) -> dict[str, int]:
    r = wintypes.RECT()
    if not user32.GetWindowRect(int(handle), ctypes.byref(r)):
        return {}
    return {"x": r.left, "y": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


def active_window() -> dict[str, Any]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {}
    return {"handle": hwnd, "title": _title(hwnd), "class": _class(hwnd),
            "process": _process(hwnd), "rect": window_rect(hwnd)}


def list_windows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd: int, _lp: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            t = _title(hwnd)
            if t:
                out.append({"handle": hwnd, "title": t, "rect": window_rect(hwnd)})
        return True

    user32.EnumWindows(proto(cb), 0)
    return out


def activate(handle: Any) -> None:
    hwnd = int(handle)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # Windows only lets the foreground process change focus; a synthetic Alt
    # press makes this process "last input" owner so SetForegroundWindow works.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)


# --- UI Automation (optional) -----------------------------------------------
def _uia():  # type: ignore[no-untyped-def]
    if os.environ.get("HERMES_TEACH_NO_UIA"):
        return None
    try:
        import uiautomation  # type: ignore[import-not-found]
        return uiautomation
    except Exception:
        return None


def _role(control_type_name: str) -> str:
    # "CheckBoxControl" -> "check_box"
    base = control_type_name.removesuffix("Control")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", base).lower()


def _info(c: Any) -> dict[str, Any]:
    auto = _uia()
    try:
        info = {"name": c.Name or "", "role": _role(c.ControlTypeName or ""),
                "automation_id": c.AutomationId or ""}
        try:
            info["is_password"] = bool(c.GetPropertyValue(auto.PropertyId.IsPasswordProperty))
        except Exception:
            info["is_password"] = False
        return info
    except Exception:
        return {}


def element_at(x: int, y: int) -> dict[str, Any]:
    auto = _uia()
    if auto is None:
        return {}
    try:
        c = auto.ControlFromPoint(x, y)
        return _info(c) if c else {}
    except Exception:
        return {}


def focused_element() -> dict[str, Any]:
    auto = _uia()
    if auto is None:
        return {}
    try:
        c = auto.GetFocusedControl()
        return _info(c) if c else {}
    except Exception:
        return {}


def find_element(handle: Any, name: str = "", role: str = "", automation_id: str = "") -> tuple[int, int] | None:
    auto = _uia()
    if auto is None or not (name or automation_id):
        return None
    try:
        win = auto.ControlFromHandle(int(handle))
        crit: dict[str, Any] = {"searchDepth": 30}
        if automation_id:
            crit["AutomationId"] = automation_id
        elif name:
            crit["Name"] = name
        c = win.Control(**crit)
        if not c.Exists(2, 0.2):
            return None
        if role and _role(c.ControlTypeName or "") != role and not automation_id:
            return None
        r = c.BoundingRectangle
        return ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    except Exception:
        return None
