"""Linux (X11) context via xdotool + /proc, optional AT-SPI2 via pyatspi.

Wayland note: global input capture and synthetic input are blocked by design
on Wayland. On GNOME/KDE Wayland sessions run the recorder inside an X11
session ("GNOME on Xorg"), or under XWayland apps only; an evdev/libei
backend is the planned route (see docs/teach-design.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

_HAS_XDOTOOL = shutil.which("xdotool") is not None


def _xdo(*args: str) -> str:
    if not _HAS_XDOTOOL:
        return ""
    try:
        r = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _geometry(wid: str) -> dict[str, int]:
    # xwininfo reports the client area exactly; `xdotool getwindowgeometry` is
    # off by the title bar height under reparenting window managers.
    if shutil.which("xwininfo"):
        try:
            r = subprocess.run(["xwininfo", "-id", wid], capture_output=True, text=True, timeout=3)
            keys = {"Absolute upper-left X": "x", "Absolute upper-left Y": "y", "Width": "width",
                    "Height": "height"}
            vals = {}
            for line in r.stdout.splitlines():
                k, _, v = line.strip().partition(":")
                if k in keys and v.strip().lstrip("-").isdigit():
                    vals[keys[k]] = int(v)
            if len(vals) == 4:
                return vals
        except subprocess.TimeoutExpired:
            pass
    out = _xdo("getwindowgeometry", "--shell", wid)
    vals: dict[str, int] = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k in ("X", "Y", "WIDTH", "HEIGHT"):
            vals[k.lower()] = int(v)
    return vals


def _process_name(wid: str) -> str:
    pid = _xdo("getwindowpid", wid)
    if pid.isdigit():
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""
    return ""


def _wm_class(wid: str) -> str:
    if shutil.which("xprop") is None:
        return ""
    try:
        r = subprocess.run(["xprop", "-id", wid, "WM_CLASS"], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return ""
    # WM_CLASS(STRING) = "instance", "Class"
    parts = r.stdout.split('"')
    return parts[3] if len(parts) >= 4 else ""


def active_window() -> dict[str, Any]:
    wid = _xdo("getactivewindow")
    if not wid:
        return {}
    info: dict[str, Any] = {"handle": wid, "title": _xdo("getwindowname", wid),
                            "class": _wm_class(wid), "process": _process_name(wid)}
    info["rect"] = _geometry(wid)
    return info


def list_windows() -> list[dict[str, Any]]:
    out = _xdo("search", "--onlyvisible", "--name", ".")
    wins = []
    for wid in out.split():
        title = _xdo("getwindowname", wid)
        if title:
            wins.append({"handle": wid, "title": title, "rect": _geometry(wid)})
    return wins


def activate(handle: Any) -> None:
    _xdo("windowactivate", "--sync", str(handle))


def window_rect(handle: Any) -> dict[str, int]:
    return _geometry(str(handle))


# --- AT-SPI2 (optional) -----------------------------------------------------
def _atspi():  # type: ignore[no-untyped-def]
    if os.environ.get("HERMES_TEACH_NO_ATSPI"):
        return None
    try:
        import pyatspi  # type: ignore[import-not-found]
        return pyatspi
    except Exception:
        return None


def _accessible_info(acc: Any) -> dict[str, Any]:
    try:
        role = acc.getRoleName().replace(" ", "_")
        return {"name": acc.name or "", "role": role, "is_password": role == "password_text"}
    except Exception:
        return {}


def element_at(x: int, y: int) -> dict[str, Any]:
    pyatspi = _atspi()
    if pyatspi is None:
        return {}
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            for win in app:
                comp = win.queryComponent()
                if comp.contains(x, y, pyatspi.DESKTOP_COORDS):
                    acc = comp.getAccessibleAtPoint(x, y, pyatspi.DESKTOP_COORDS)
                    while acc is not None:
                        try:
                            inner = acc.queryComponent().getAccessibleAtPoint(x, y, pyatspi.DESKTOP_COORDS)
                        except Exception:
                            inner = None
                        if inner is None or inner == acc:
                            break
                        acc = inner
                    return _accessible_info(acc) if acc is not None else {}
    except Exception:
        return {}
    return {}


def focused_element() -> dict[str, Any]:
    pyatspi = _atspi()
    if pyatspi is None:
        return {}
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            for win in app:
                if win.getState().contains(pyatspi.STATE_ACTIVE):
                    found = pyatspi.findDescendant(
                        win, lambda a: a.getState().contains(pyatspi.STATE_FOCUSED))
                    return _accessible_info(found) if found is not None else {}
    except Exception:
        return {}
    return {}


def find_element(handle: Any, name: str = "", role: str = "", automation_id: str = "") -> tuple[int, int] | None:
    pyatspi = _atspi()
    if pyatspi is None or not (name or role):
        return None
    try:
        title = _xdo("getwindowname", str(handle))
        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            for win in app:
                if win.name != title:
                    continue
                acc = pyatspi.findDescendant(
                    win, lambda a: (not name or a.name == name)
                    and (not role or a.getRoleName().replace(" ", "_") == role))
                if acc is not None:
                    ext = acc.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                    return (ext.x + ext.width // 2, ext.y + ext.height // 2)
    except Exception:
        return None
    return None
