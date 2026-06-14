"""Hermes GUI Automation — input subpackage."""

from hermes_gui.input.mouse import move, click, double_click, right_click, drag, get_position
from hermes_gui.input.keyboard import type_text, press_key, hotkey
from hermes_gui.input.clipboard import get_clipboard_text, set_clipboard_text

__all__ = [
    "move", "click", "double_click", "right_click", "drag", "get_position",
    "type_text", "press_key", "hotkey",
    "get_clipboard_text", "set_clipboard_text",
]
