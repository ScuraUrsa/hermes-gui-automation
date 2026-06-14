"""Hermes GUI Automation — core orchestration and public API.

This module provides the main entry point for all GUI automation operations.
It handles backend selection, fallback logic, concurrency control, and
screenshot logging.
"""

import threading
import time
from typing import Optional

from hermes_gui.config import config
from hermes_gui.errors import (
    BackendNotAvailable,
    ConcurrencyError,
    ElementNotFound,
    GUIError,
    TimeoutError,
)
from hermes_gui.types import BoundingBox, Element, Screenshot, TextBlock, Window

# Lazy imports for backends — loaded on first use
_atspi_backend = None
_visual_backend = None
_vlm_backend = None
_browser_backend = None

# Concurrency lock
_lock = threading.Lock()
_current_operation: Optional[str] = None


def _acquire_lock(operation: str, timeout: float = 30.0) -> bool:
    """Acquire the global GUI operation lock."""
    global _current_operation
    acquired = _lock.acquire(timeout=timeout)
    if not acquired:
        raise ConcurrencyError()
    _current_operation = operation
    return True


def _release_lock() -> None:
    """Release the global GUI operation lock."""
    global _current_operation
    _current_operation = None
    _lock.release()


def _get_backend(name: str):
    """Get or initialize a backend by name."""
    global _atspi_backend, _visual_backend, _vlm_backend, _browser_backend

    if name == "atspi":
        if _atspi_backend is None:
            from hermes_gui.backends.atspi import ATSPIBackend
            _atspi_backend = ATSPIBackend()
        return _atspi_backend

    elif name == "visual":
        if _visual_backend is None:
            from hermes_gui.backends.visual import VisualBackend
            _visual_backend = VisualBackend()
        return _visual_backend

    elif name == "vlm":
        if _vlm_backend is None:
            from hermes_gui.backends.vlm import VLMBackend
            _vlm_backend = VLMBackend()
        return _vlm_backend

    elif name == "browser":
        if _browser_backend is None:
            from hermes_gui.backends.browser import BrowserBackend
            _browser_backend = BrowserBackend()
        return _browser_backend

    raise BackendNotAvailable(name, "Unknown backend name")


# ============================================================
# Public API — Screen Capture
# ============================================================

def gui_screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    window_title: Optional[str] = None,
) -> Screenshot:
    """Capture full screen, a region (x,y,w,h), or a specific window.

    Args:
        region: Optional (x, y, width, height) tuple for partial capture.
        window_title: Optional window title substring for window-specific capture.

    Returns:
        Screenshot dataclass with PIL Image and metadata.
    """
    from hermes_gui.capture.screen import capture_screenshot
    return capture_screenshot(region=region, window_title=window_title)


# ============================================================
# Public API — OCR
# ============================================================

def gui_ocr(
    screenshot: Optional[Screenshot] = None,
    region: Optional[tuple[int, int, int, int]] = None,
    language: str = "eng",
) -> list[TextBlock]:
    """Extract all text from a screenshot or region.

    Args:
        screenshot: Optional existing Screenshot. If None, captures full screen.
        region: Optional (x, y, width, height) to OCR only a region.
        language: Tesseract language code (default: eng).

    Returns:
        List of TextBlock objects with text, bounding box, and confidence.
    """
    from hermes_gui.ocr.tesseract import ocr_screenshot
    if screenshot is None:
        screenshot = gui_screenshot(region=region)
    return ocr_screenshot(screenshot, language=language)


# ============================================================
# Public API — Element Finding
# ============================================================

def gui_find(
    text: str,
    timeout: float = 10.0,
    prefer_backend: Optional[str] = None,
) -> Element:
    """Find a UI element by its visible text label.

    Searches backends in order: AT-SPI2 → Visual (OCR) → VLM.
    Falls back to next backend if current one fails.

    Args:
        text: The visible text to search for (e.g., "Submit", "Cancel").
        timeout: Maximum time to wait for the element.
        prefer_backend: Force a specific backend ("atspi", "visual", "vlm").

    Returns:
        Element dataclass with position, role, and confidence.

    Raises:
        ElementNotFound: If no backend can find the element.
    """
    _acquire_lock(f"find:{text}")
    try:
        backends_tried: list[str] = []

        if prefer_backend:
            order = [prefer_backend]
        else:
            order = config.backend_order

        for backend_name in order:
            try:
                backend = _get_backend(backend_name)
                element = backend.find_element(text, timeout=timeout)
                if element is not None:
                    element.backend = backend_name
                    return element
                backends_tried.append(backend_name)
            except BackendNotAvailable:
                backends_tried.append(backend_name)
                continue
            except GUIError:
                backends_tried.append(backend_name)
                continue

        raise ElementNotFound(text, backends_tried)
    finally:
        _release_lock()


def gui_find_by_prompt(
    prompt: str,
    timeout: float = 15.0,
) -> Element:
    """Find a UI element by natural language description using VLM.

    Args:
        prompt: Natural language description (e.g., "the blue Submit button").
        timeout: Maximum time to wait.

    Returns:
        Element dataclass.
    """
    _acquire_lock(f"find_by_prompt:{prompt[:50]}")
    try:
        backend = _get_backend("vlm")
        element = backend.find_by_prompt(prompt, timeout=timeout)
        element.backend = "vlm"
        return element
    finally:
        _release_lock()


# ============================================================
# Public API — Mouse Control
# ============================================================

def gui_click(
    element: Optional[Element] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    button: str = "left",
) -> None:
    """Click on an element (center) or at specific coordinates.

    Args:
        element: Element to click (clicks at center of bounding box).
        x, y: Explicit coordinates (used if element is None).
        button: Mouse button: "left", "right", "middle".
    """
    from hermes_gui.input.mouse import click
    if element is not None:
        cx, cy = element.bbox.center
        click(cx, cy, button=button)
    elif x is not None and y is not None:
        click(x, y, button=button)
    else:
        raise GUIError("gui_click requires either an element or (x, y) coordinates")


def gui_double_click(
    element: Optional[Element] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> None:
    """Double-click on an element or at coordinates."""
    from hermes_gui.input.mouse import double_click
    if element is not None:
        cx, cy = element.bbox.center
        double_click(cx, cy)
    elif x is not None and y is not None:
        double_click(x, y)
    else:
        raise GUIError("gui_double_click requires either an element or (x, y) coordinates")


def gui_right_click(
    element: Optional[Element] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> None:
    """Right-click on an element or at coordinates."""
    from hermes_gui.input.mouse import right_click
    if element is not None:
        cx, cy = element.bbox.center
        right_click(cx, cy)
    elif x is not None and y is not None:
        right_click(x, y)
    else:
        raise GUIError("gui_right_click requires either an element or (x, y) coordinates")


def gui_move(x: int, y: int) -> None:
    """Move mouse cursor to (x, y)."""
    from hermes_gui.input.mouse import move
    move(x, y)


def gui_drag(
    start: tuple[int, int],
    end: tuple[int, int],
    button: str = "left",
) -> None:
    """Drag from start coordinates to end coordinates."""
    from hermes_gui.input.mouse import drag
    drag(start[0], start[1], end[0], end[1], button=button)


# ============================================================
# Public API — Keyboard Input
# ============================================================

def gui_type(text: str, interval: Optional[float] = None) -> None:
    """Type text character by character.

    Args:
        text: The text to type.
        interval: Delay between keystrokes in seconds (default from config).
    """
    from hermes_gui.input.keyboard import type_text
    interval = interval if interval is not None else config.type_interval
    type_text(text, interval=interval)


def gui_press(key: str) -> None:
    """Press a single key (e.g., 'Return', 'Tab', 'Escape', 'F5')."""
    from hermes_gui.input.keyboard import press_key
    press_key(key)


def gui_hotkey(*keys: str) -> None:
    """Press a key combination (e.g., gui_hotkey('ctrl', 'c'))."""
    from hermes_gui.input.keyboard import hotkey
    hotkey(*keys)


# ============================================================
# Public API — Window Management
# ============================================================

def gui_list_windows() -> list[Window]:
    """List all open windows with title, PID, geometry."""
    from hermes_gui.capture.window import list_windows
    return list_windows()


def gui_focus_window(title: Optional[str] = None, pid: Optional[int] = None) -> Window:
    """Focus a window by title substring or PID.

    Args:
        title: Substring to match in window title.
        pid: Process ID of the window to focus.

    Returns:
        The focused Window object.

    Raises:
        WindowNotFound: If no matching window found.
    """
    from hermes_gui.capture.window import focus_window
    return focus_window(title=title, pid=pid)


def gui_get_active_window() -> Window:
    """Get the currently active/focused window."""
    from hermes_gui.capture.window import get_active_window
    return get_active_window()


def gui_close_window(title: str) -> None:
    """Close a window by title substring."""
    from hermes_gui.capture.window import close_window
    close_window(title)


# ============================================================
# Public API — Clipboard
# ============================================================

def gui_copy() -> None:
    """Copy current selection to clipboard (Ctrl+C)."""
    gui_hotkey("ctrl", "c")


def gui_paste() -> None:
    """Paste clipboard content (Ctrl+V)."""
    gui_hotkey("ctrl", "v")


def gui_get_clipboard() -> str:
    """Read current clipboard text content."""
    from hermes_gui.input.clipboard import get_clipboard_text
    return get_clipboard_text()


# ============================================================
# Public API — Wait Conditions
# ============================================================

def gui_wait_for_text(
    text: str,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> Element:
    """Block until specified text appears on screen.

    Args:
        text: Text to wait for.
        timeout: Maximum time to wait in seconds.
        interval: Polling interval in seconds.

    Returns:
        Element containing the found text.

    Raises:
        TimeoutError: If text doesn't appear within timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            element = gui_find(text, timeout=interval)
            return element
        except ElementNotFound:
            time.sleep(interval)
    raise TimeoutError(f"text '{text}'", timeout)


def gui_wait_for_window(
    title: str,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> Window:
    """Block until a window with specified title appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        windows = gui_list_windows()
        for w in windows:
            if title.lower() in w.title.lower():
                return w
        time.sleep(interval)
    raise TimeoutError(f"window '{title}'", timeout)


# ============================================================
# Public API — Form Filling
# ============================================================

def gui_fill_form(
    fields: dict[str, str],
    submit_button: Optional[str] = None,
) -> None:
    """Fill multiple form fields and optionally submit.

    Args:
        fields: Dict mapping field labels to values.
        submit_button: Optional text of the submit button to click after filling.
    """
    _acquire_lock("fill_form")
    try:
        for label, value in fields.items():
            element = gui_find(label)
            gui_click(element)
            gui_type(value)
            gui_press("Tab")  # Move to next field

        if submit_button:
            submit = gui_find(submit_button)
            gui_click(submit)
    finally:
        _release_lock()


# ============================================================
# Public API — Application Launch
# ============================================================

def gui_launch(app_name: str) -> Window:
    """Launch an application by name and return its window.

    Args:
        app_name: Application name or command (e.g., "firefox", "gedit").

    Returns:
        Window object for the launched application.
    """
    import subprocess
    _acquire_lock(f"launch:{app_name}")
    try:
        subprocess.Popen([app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return gui_wait_for_window(app_name, timeout=15.0)
    finally:
        _release_lock()


# ============================================================
# Public API — Browser (specialized)
# ============================================================

def gui_browser_navigate(url: str) -> None:
    """Navigate browser to a URL."""
    backend = _get_backend("browser")
    backend.navigate(url)


def gui_browser_click(selector: str) -> None:
    """Click an element in the browser by CSS selector."""
    backend = _get_backend("browser")
    backend.click(selector)


def gui_browser_type(selector: str, text: str) -> None:
    """Type text into a browser input by CSS selector."""
    backend = _get_backend("browser")
    backend.type_text(selector, text)


def gui_browser_snapshot() -> str:
    """Get accessibility tree snapshot of current browser page."""
    backend = _get_backend("browser")
    return backend.snapshot()
