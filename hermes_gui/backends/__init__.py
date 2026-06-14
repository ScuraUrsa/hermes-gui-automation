"""Hermes GUI Automation — backends package."""

from hermes_gui.backends.atspi import ATSPIBackend
from hermes_gui.backends.visual import VisualBackend
from hermes_gui.backends.vlm import VLMBackend
from hermes_gui.backends.browser import BrowserBackend

__all__ = ["ATSPIBackend", "VisualBackend", "VLMBackend", "BrowserBackend"]
