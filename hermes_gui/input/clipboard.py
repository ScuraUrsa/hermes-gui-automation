"""Hermes GUI Automation — clipboard management via xclip."""

import subprocess

from hermes_gui.config import config
from hermes_gui.errors import InputError


def get_clipboard_text() -> str:
    """Read current clipboard text content."""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            check=False, capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            # An empty clipboard is a normal state, not an error:
            # xclip reports "Error: target STRING not available".
            if "not available" in result.stderr:
                return ""
            raise InputError("xclip", result.stderr.strip())
        return result.stdout
    except FileNotFoundError:
        raise InputError("xclip", "xclip not installed. sudo apt-get install xclip")


def set_clipboard_text(text: str) -> None:
    """Set clipboard text content."""
    try:
        # xclip forks a background process that keeps serving the selection.
        # That child inherits stdout/stderr, so capturing them would block
        # until it exits (i.e. until something else takes the clipboard).
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-i"],
            input=text, check=False, text=True, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xclip", f"xclip exited with status {result.returncode}")
    except FileNotFoundError:
        raise InputError("xclip", "xclip not installed. sudo apt-get install xclip")
