"""Hermes GUI Automation — clipboard management via xclip."""

import subprocess

from hermes_gui.config import config
from hermes_gui.errors import InputError


def get_clipboard_text() -> str:
    """Read current clipboard text content."""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xclip", result.stderr.strip())
        return result.stdout
    except FileNotFoundError:
        raise InputError("xclip", "xclip not installed. sudo apt-get install xclip")


def set_clipboard_text(text: str) -> None:
    """Set clipboard text content."""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-i"],
            input=text, capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xclip", result.stderr.strip())
    except FileNotFoundError:
        raise InputError("xclip", "xclip not installed. sudo apt-get install xclip")
