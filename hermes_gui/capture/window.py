"""Hermes GUI Automation — window management via wmctrl + xdotool."""

import subprocess

from hermes_gui.config import config
from hermes_gui.errors import InputError, WindowNotFound
from hermes_gui.types import BoundingBox, Window


def _wmctrl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["wmctrl"] + list(args),
            check=False, capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("wmctrl", result.stderr.strip())
        return result.stdout.strip()
    except FileNotFoundError:
        raise InputError("wmctrl", "wmctrl not installed. sudo apt-get install wmctrl")


def _xdotool(*args: str) -> str:
    try:
        result = subprocess.run(
            ["xdotool"] + list(args),
            check=False, capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xdotool", result.stderr.strip())
        return result.stdout.strip()
    except FileNotFoundError:
        raise InputError("xdotool", "xdotool not installed")


def list_windows() -> list[Window]:
    """List all open windows."""
    # Columns: id desktop pid x y width height wm_class client_host title
    out = _wmctrl("-l", "-p", "-G", "-x")
    windows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 9)
        if len(parts) < 8:
            continue
        try:
            windows.append(Window(
                id=parts[0],
                desktop=int(parts[1]),
                pid=int(parts[2]),
                x=int(parts[3]),
                y=int(parts[4]),
                width=int(parts[5]),
                height=int(parts[6]),
                class_name=parts[7],
                title=parts[9] if len(parts) > 9 else "",
            ))
        except (ValueError, IndexError):
            continue
    return windows


def focus_window(title: str | None = None, pid: int | None = None) -> Window:
    """Focus a window by title substring or PID."""
    windows = list_windows()
    for w in windows:
        if title and title.lower() in w.title.lower():
            _wmctrl("-i", "-a", w.id)
            w.is_active = True
            return w
        if pid and w.pid == pid:
            _wmctrl("-i", "-a", w.id)
            w.is_active = True
            return w
    raise WindowNotFound(title or f"pid={pid}")


def get_active_window() -> Window:
    """Get the currently active window."""
    try:
        # xdotool prints a decimal window id; wmctrl lists them in hex.
        active_id = int(_xdotool("getactivewindow"))
    except (InputError, ValueError):
        raise WindowNotFound("active")
    windows = list_windows()
    for w in windows:
        if int(w.id, 16) == active_id:
            w.is_active = True
            return w
    raise WindowNotFound("active")


def get_window_geometry(title: str) -> BoundingBox:
    """Get geometry of a window by title."""
    windows = list_windows()
    for w in windows:
        if title.lower() in w.title.lower():
            return BoundingBox(w.x, w.y, w.width, w.height)
    raise WindowNotFound(title)


def close_window(title: str) -> None:
    """Close a window gracefully by title."""
    windows = list_windows()
    for w in windows:
        if title.lower() in w.title.lower():
            _wmctrl("-i", "-c", w.id)
            return
    raise WindowNotFound(title)


def resize_window(title: str, width: int, height: int) -> None:
    """Resize a window."""
    windows = list_windows()
    for w in windows:
        if title.lower() in w.title.lower():
            _wmctrl("-i", "-r", w.id, "-e", f"0,-1,-1,{width},{height}")
            return
    raise WindowNotFound(title)
