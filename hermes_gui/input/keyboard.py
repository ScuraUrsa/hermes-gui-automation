"""Hermes GUI Automation — keyboard input via xdotool."""

import subprocess

from hermes_gui.config import config
from hermes_gui.errors import InputError


def _xdotool(*args: str) -> None:
    try:
        result = subprocess.run(
            ["xdotool"] + list(args),
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xdotool", result.stderr.strip())
    except FileNotFoundError:
        raise InputError("xdotool", "xdotool not installed. sudo apt-get install xdotool")


def type_text(text: str, interval: float = 0.01) -> None:
    """Type text character by character with configurable interval."""
    _xdotool("type", "--delay", str(int(interval * 1000)), text)


def press_key(key: str) -> None:
    """Press a single key. Use X11 keysym names: Return, Tab, Escape, F5, etc."""
    _xdotool("key", key)


def hotkey(*keys: str) -> None:
    """Press a key combination. e.g., hotkey('ctrl', 'c') for Ctrl+C."""
    _xdotool("key", "+".join(keys))
