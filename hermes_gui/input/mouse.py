"""Hermes GUI Automation — mouse control via xdotool."""

import subprocess
import time

from hermes_gui.config import config
from hermes_gui.errors import InputError


def _xdotool(*args: str) -> str:
    """Run xdotool command and return stdout."""
    try:
        result = subprocess.run(
            ["xdotool"] + list(args),
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": config.display},
        )
        if result.returncode != 0:
            raise InputError("xdotool", result.stderr.strip())
        return result.stdout.strip()
    except FileNotFoundError:
        raise InputError("xdotool", "xdotool not installed. Install: sudo apt-get install xdotool")
    except subprocess.TimeoutExpired:
        raise InputError("xdotool", "Command timed out")


def move(x: int, y: int) -> None:
    """Move mouse cursor to absolute coordinates."""
    _xdotool("mousemove", str(x), str(y))


def click(x: int, y: int, button: str = "left") -> None:
    """Click at coordinates."""
    move(x, y)
    time.sleep(0.05)
    _xdotool("click", str(button_map(button)))


def double_click(x: int, y: int) -> None:
    """Double-click at coordinates."""
    move(x, y)
    time.sleep(0.05)
    _xdotool("click", "--repeat", "2", "1")


def right_click(x: int, y: int) -> None:
    """Right-click at coordinates."""
    click(x, y, button="right")


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> None:
    """Drag from (x1,y1) to (x2,y2)."""
    move(x1, y1)
    time.sleep(0.05)
    _xdotool("mousedown", str(button_map(button)))
    time.sleep(0.05)
    move(x2, y2)
    time.sleep(0.05)
    _xdotool("mouseup", str(button_map(button)))


def get_position() -> tuple[int, int]:
    """Get current mouse position."""
    out = _xdotool("getmouselocation")
    # Parse "x:123 y:456 screen:0 window:12345"
    parts = out.split()
    x = int(parts[0].split(":")[1])
    y = int(parts[1].split(":")[1])
    return (x, y)


def button_map(button: str) -> int:
    """Map button name to xdotool button number."""
    return {"left": 1, "middle": 2, "right": 3}.get(button, 1)
