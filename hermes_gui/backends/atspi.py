"""Hermes GUI Automation — AT-SPI2 backend.

Uses dogtail and pyatspi2 to interact with applications that expose
accessibility trees (GTK3/4, Qt5/6, LibreOffice, Firefox chrome).
"""

import time
from typing import Optional

from hermes_gui.errors import BackendNotAvailable
from hermes_gui.types import BoundingBox, Element


class ATSPIBackend:
    """Backend using AT-SPI2 accessibility protocol."""

    def __init__(self):
        self._available = False
        try:
            import pyatspi
            self._pyatspi = pyatspi
            self._available = True
        except ImportError:
            pass

    def _check_available(self):
        if not self._available:
            raise BackendNotAvailable(
                "atspi",
                "pyatspi2 not installed. Install: sudo apt-get install python3-pyatspi"
            )

    def find_element(self, text: str, timeout: float = 10.0) -> Optional[Element]:
        """Find a UI element by its visible text/name using AT-SPI2."""
        self._check_available()
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                registry = self._pyatspi.Registry
                desktop = registry.getDesktop(0)

                for app in desktop:
                    for window in app:
                        element = self._search_widget(window, text)
                        if element:
                            return element
            except Exception:
                pass

            time.sleep(0.1)

        return None

    def _search_widget(self, widget, text: str, depth: int = 0) -> Optional[Element]:
        """Recursively search widget tree for matching text."""
        if depth > 50:  # Prevent infinite recursion
            return None

        try:
            name = getattr(widget, 'name', '')
            role = getattr(widget, 'role', '')
            role_name = getattr(role, 'roleName', '') if role else ''

            if text.lower() in name.lower():
                extents = getattr(widget, 'extents', None)
                if extents:
                    bbox = BoundingBox(extents.x, extents.y, extents.width, extents.height)
                else:
                    bbox = BoundingBox(0, 0, 0, 0)

                return Element(
                    role=role_name,
                    name=name,
                    bbox=bbox,
                    confidence=1.0,
                    properties={"widget": str(widget)},
                )

            # Search children
            for i in range(getattr(widget, 'childCount', 0)):
                try:
                    child = widget.getChildAtIndex(i)
                    result = self._search_widget(child, text, depth + 1)
                    if result:
                        return result
                except Exception:
                    continue

        except Exception:
            pass

        return None

    def click_element(self, element: Element) -> None:
        """Click an element via AT-SPI2 action interface."""
        self._check_available()
        widget = element.properties.get("widget")
        if widget:
            try:
                action = widget.queryAction()
                for i in range(action.nActions):
                    if action.getName(i) in ("click", "press", "activate"):
                        action.doAction(i)
                        return
            except Exception:
                pass

        # Fallback: click at coordinates
        from hermes_gui.input.mouse import click
        cx, cy = element.bbox.center
        click(cx, cy)

    def type_text(self, element: Element, text: str) -> None:
        """Type text into an element via AT-SPI2 text interface."""
        self._check_available()
        widget = element.properties.get("widget")
        if widget:
            try:
                editable = widget.queryEditableText()
                editable.setTextContents(text)
                return
            except Exception:
                pass

        # Fallback: click then type via keyboard
        self.click_element(element)
        from hermes_gui.input.keyboard import type_text as kb_type
        kb_type(text)
