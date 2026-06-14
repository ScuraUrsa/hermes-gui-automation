"""Hermes GUI Automation — capture subpackage."""

from hermes_gui.capture.screen import capture_screenshot
from hermes_gui.capture.window import (
    list_windows, focus_window, get_active_window, get_window_geometry,
    close_window, resize_window,
)

__all__ = [
    "capture_screenshot",
    "list_windows", "focus_window", "get_active_window",
    "get_window_geometry", "close_window", "resize_window",
]
