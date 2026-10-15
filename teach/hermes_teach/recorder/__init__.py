"""Recorders: global desktop input (Windows, Linux/X11) and DOM-level browser."""

__all__ = ["DesktopRecorder", "BrowserRecorder"]


def __getattr__(name: str):  # lazy: pynput needs a display at import time
    if name == "DesktopRecorder":
        from hermes_teach.recorder.desktop import DesktopRecorder
        return DesktopRecorder
    if name == "BrowserRecorder":
        from hermes_teach.recorder.browser import BrowserRecorder
        return BrowserRecorder
    raise AttributeError(name)
