"""Hermes GUI Automation — display detection (X11 vs Wayland)."""

import os


def detect_display_server() -> str:
    """Detect whether running on X11 or Wayland.

    Returns:
        "x11", "wayland", or "unknown"
    """
    # Check XDG_SESSION_TYPE (most reliable on modern systems)
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type in ("x11", "wayland"):
        return session_type

    # Check WAYLAND_DISPLAY
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"

    # Check DISPLAY (X11)
    if os.environ.get("DISPLAY"):
        return "x11"

    return "unknown"


def is_xvfb() -> bool:
    """Check if running on Xvfb virtual framebuffer."""
    display = os.environ.get("DISPLAY", "")
    # Xvfb typically uses high display numbers like :99
    # This is a heuristic — not definitive
    try:
        import subprocess
        result = subprocess.run(
            ["xdpyinfo"],
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": display},
        )
        return "Xvfb" in result.stdout
    except Exception:
        return False


def get_screen_resolution() -> tuple[int, int]:
    """Get current screen resolution (width, height)."""
    try:
        import subprocess
        result = subprocess.run(
            ["xdpyinfo"],
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": os.environ.get("DISPLAY", ":99")},
        )
        for line in result.stdout.splitlines():
            if "dimensions:" in line:
                parts = line.split()
                dims = parts[1].split("x")
                return int(dims[0]), int(dims[1])
    except Exception:
        pass
    return 1920, 1080  # Default fallback
