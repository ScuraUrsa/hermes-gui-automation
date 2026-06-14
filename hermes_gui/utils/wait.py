"""Hermes GUI Automation — wait condition utilities."""

import time

from hermes_gui.errors import TimeoutError


def wait_for_condition(
    condition_fn,
    timeout: float = 30.0,
    interval: float = 0.5,
    description: str = "condition",
):
    """Generic wait-for-condition loop.

    Args:
        condition_fn: Callable that returns truthy when condition is met.
        timeout: Maximum time to wait in seconds.
        interval: Polling interval in seconds.
        description: Human-readable description for error messages.

    Returns:
        The truthy value returned by condition_fn.

    Raises:
        TimeoutError: If condition is not met within timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = condition_fn()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError(description, timeout)


def wait_for_text_on_screen(
    text: str,
    timeout: float = 30.0,
    interval: float = 0.5,
    language: str = "eng",
):
    """Wait until specific text appears anywhere on screen (via OCR).

    Args:
        text: Text to wait for.
        timeout: Maximum time to wait.
        interval: Polling interval.
        language: OCR language.

    Returns:
        TextBlock containing the found text.
    """
    from hermes_gui.core import gui_screenshot, gui_ocr

    def _check():
        screenshot = gui_screenshot()
        blocks = gui_ocr(screenshot, language=language)
        for block in blocks:
            if text.lower() in block.text.lower():
                return block
        return None

    return wait_for_condition(_check, timeout, interval, f"text '{text}' on screen")


def wait_for_window_title(
    title: str,
    timeout: float = 30.0,
    interval: float = 0.5,
):
    """Wait until a window with specified title appears.

    Args:
        title: Window title substring to match.
        timeout: Maximum time to wait.
        interval: Polling interval.

    Returns:
        Window object.
    """
    from hermes_gui.core import gui_list_windows

    def _check():
        for w in gui_list_windows():
            if title.lower() in w.title.lower():
                return w
        return None

    return wait_for_condition(_check, timeout, interval, f"window '{title}'")


def wait_for_window_closed(
    title: str,
    timeout: float = 30.0,
    interval: float = 0.5,
):
    """Wait until a window with specified title is closed.

    Args:
        title: Window title substring to match.
        timeout: Maximum time to wait.
        interval: Polling interval.
    """
    from hermes_gui.core import gui_list_windows

    def _check():
        for w in gui_list_windows():
            if title.lower() in w.title.lower():
                return False  # Still open
        return True  # Closed

    wait_for_condition(_check, timeout, interval, f"window '{title}' closed")
