"""Hermes GUI Automation — capture subpackage."""

from hermes_gui.capture.screen import capture_screenshot
from hermes_gui.capture.window import (
    close_window,
    focus_window,
    get_active_window,
    get_window_geometry,
    list_windows,
    resize_window,
)

__all__ = [
    "capture_screenshot",
    "close_window",
    "focus_window",
    "get_active_window",
    "get_window_geometry",
    "list_windows",
    "resize_window",
]
