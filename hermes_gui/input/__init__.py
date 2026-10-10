"""Hermes GUI Automation — input subpackage."""

from hermes_gui.input.clipboard import get_clipboard_text, set_clipboard_text
from hermes_gui.input.keyboard import hotkey, press_key, type_text
from hermes_gui.input.mouse import (
    click,
    double_click,
    drag,
    get_position,
    move,
    right_click,
)

__all__ = [
    "click",
    "double_click",
    "drag",
    "get_clipboard_text",
    "get_position",
    "hotkey",
    "move",
    "press_key",
    "right_click",
    "set_clipboard_text",
    "type_text",
]
