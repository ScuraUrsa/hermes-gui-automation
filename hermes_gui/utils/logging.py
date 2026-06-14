"""Hermes GUI Automation — screenshot logging for debugging."""

import os
import time
from typing import Optional

from hermes_gui.config import config


def log_screenshot(
    screenshot,
    operation: str,
    prefix: str = "op",
) -> Optional[str]:
    """Save a screenshot to the log directory for debugging.

    Args:
        screenshot: The Screenshot to save.
        operation: Description of the operation (e.g., "click_Submit").
        prefix: File prefix (default: "op").

    Returns:
        Path to saved file, or None if logging is disabled.
    """
    if not config.screenshot_log_enabled:
        return None

    os.makedirs(config.screenshot_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_op = operation.replace(" ", "_").replace("/", "_")[:50]
    filename = f"{prefix}_{timestamp}_{safe_op}.png"
    path = os.path.join(config.screenshot_dir, filename)

    screenshot.image.save(path, "PNG")
    return path


def log_operation(
    operation: str,
    backend: str,
    duration_ms: float,
    success: bool,
    details: str = "",
) -> None:
    """Log a GUI operation to the operations log file.

    Args:
        operation: Operation name (e.g., "find:Submit").
        backend: Backend used (atspi, visual, vlm, browser).
        duration_ms: Operation duration in milliseconds.
        success: Whether the operation succeeded.
        details: Additional details (element info, error message).
    """
    if not config.screenshot_log_enabled:
        return

    os.makedirs(config.screenshot_dir, exist_ok=True)
    log_path = os.path.join(config.screenshot_dir, "operations.log")

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    status = "OK" if success else "FAIL"
    line = f"{timestamp} [{status}] {operation} backend={backend} duration={duration_ms:.0f}ms {details}\n"

    with open(log_path, "a") as f:
        f.write(line)


def cleanup_old_screenshots(max_age_seconds: int = 300) -> int:
    """Delete screenshots older than max_age_seconds. Returns count deleted."""
    if not os.path.isdir(config.screenshot_dir):
        return 0

    now = time.time()
    deleted = 0
    for fname in os.listdir(config.screenshot_dir):
        if not fname.endswith(".png"):
            continue
        path = os.path.join(config.screenshot_dir, fname)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                os.unlink(path)
                deleted += 1
        except OSError:
            pass
    return deleted
