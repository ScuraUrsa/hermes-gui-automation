"""Hermes GUI Automation — OpenCV template matching for UI elements."""

from typing import Optional

from hermes_gui.errors import ElementNotFound
from hermes_gui.types import BoundingBox, Element, Screenshot


def match_template(
    template_path: str,
    screenshot: Screenshot,
    threshold: float = 0.8,
) -> Optional[Element]:
    """Find a UI element by image template matching.

    Args:
        template_path: Path to template image (PNG of the button/icon to find).
        screenshot: Screenshot to search in.
        threshold: Match confidence threshold (0.0-1.0, default 0.8).

    Returns:
        Element if found, None otherwise.
    """
    try:
        import cv2
    except ImportError:
        raise ElementNotFound(template_path, ["visual"])

    template = cv2.imread(template_path)
    if template is None:
        raise ElementNotFound(template_path, ["visual"])

    screen_np = cv2.cvtColor(
        screenshot.image.convert("RGB"),
        cv2.COLOR_RGB2BGR,
    )

    result = cv2.matchTemplate(screen_np, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        h, w = template.shape[:2]
        return Element(
            role="template_match",
            name=template_path,
            bbox=BoundingBox(max_loc[0], max_loc[1], w, h),
            confidence=float(max_val),
        )

    return None


def match_all_templates(
    template_path: str,
    screenshot: Screenshot,
    threshold: float = 0.8,
) -> list[Element]:
    """Find ALL occurrences of a template in a screenshot.

    Returns list of Elements sorted by confidence descending.
    """
    try:
        import cv2
    except ImportError:
        return []

    template = cv2.imread(template_path)
    if template is None:
        return []

    screen_np = cv2.cvtColor(
        screenshot.image.convert("RGB"),
        cv2.COLOR_RGB2BGR,
    )

    result = cv2.matchTemplate(screen_np, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]

    locations = []
    result_copy = result.copy()
    while True:
        _, max_val, _, max_loc = cv2.minMaxLoc(result_copy)
        if max_val < threshold:
            break
        locations.append((max_loc, max_val))
        # Zero out the found region to find next match
        cv2.rectangle(
            result_copy,
            max_loc,
            (max_loc[0] + w, max_loc[1] + h),
            0,
            -1,
        )

    return [
        Element(
            role="template_match",
            name=template_path,
            bbox=BoundingBox(loc[0], loc[1], w, h),
            confidence=float(conf),
        )
        for loc, conf in sorted(locations, key=lambda x: x[1], reverse=True)
    ]
