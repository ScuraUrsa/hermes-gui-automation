"""Hermes GUI Automation — screenshot capture via Python MSS."""

import time
from typing import Optional

from hermes_gui.config import config
from hermes_gui.errors import DisplayError
from hermes_gui.types import BoundingBox, Screenshot


def capture_screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    window_title: Optional[str] = None,
) -> Screenshot:
    """Capture full screen, a region, or a specific window.

    Args:
        region: Optional (x, y, width, height) for partial capture.
        window_title: Optional window title for window-specific capture.

    Returns:
        Screenshot with PIL Image and metadata.
    """
    try:
        from mss import mss
    except ImportError:
        raise DisplayError("Python MSS not installed. Install: pip install mss")

    with mss(display=config.display) as sct:
        if region:
            monitor = {"left": region[0], "top": region[1],
                       "width": region[2], "height": region[3]}
        elif window_title:
            from hermes_gui.capture.window import get_window_geometry
            geo = get_window_geometry(window_title)
            monitor = {"left": geo.x, "top": geo.y,
                       "width": geo.width, "height": geo.height}
        else:
            monitor = sct.monitors[0]  # Full primary monitor

        img = sct.grab(monitor)
        from PIL import Image
        pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")

        return Screenshot(
            image=pil_img,
            width=pil_img.width,
            height=pil_img.height,
            timestamp=time.time(),
            region=BoundingBox(monitor["left"], monitor["top"],
                               monitor["width"], monitor["height"]) if region else None,
            window_title=window_title,
        )
