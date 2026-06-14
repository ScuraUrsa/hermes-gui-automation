"""Hermes GUI Automation — Visual backend (OCR + template matching).

Uses Tesseract OCR and OpenCV template matching to find UI elements
on screen. Works with ANY application that displays visible text.
"""

import time
from typing import Optional

from hermes_gui.config import config
from hermes_gui.errors import BackendNotAvailable, ElementNotFound
from hermes_gui.types import BoundingBox, Element, Screenshot


class VisualBackend:
    """Backend using OCR + template matching for visual UI interaction."""

    def __init__(self):
        self._ocr_available = False
        self._cv_available = False
        try:
            import pytesseract
            self._pytesseract = pytesseract
            self._ocr_available = True
        except ImportError:
            pass
        try:
            import cv2
            self._cv2 = cv2
            self._cv_available = True
        except ImportError:
            pass

    def _check_ocr(self):
        if not self._ocr_available:
            raise BackendNotAvailable("visual", "Tesseract OCR not installed. Install: pip install pytesseract")

    def find_element(self, text: str, timeout: float = 10.0) -> Optional[Element]:
        """Find a UI element by its visible text using OCR."""
        self._check_ocr()
        deadline = time.time() + timeout

        while time.time() < deadline:
            from hermes_gui.capture.screen import capture_screenshot
            screenshot = capture_screenshot()

            # OCR the screenshot
            try:
                ocr_data = self._pytesseract.image_to_data(
                    screenshot.image,
                    lang=config.tesseract_languages,
                    output_type=self._pytesseract.Output.DICT,
                )
            except Exception:
                time.sleep(0.2)
                continue

            # Search for matching text
            for i, word in enumerate(ocr_data.get("text", [])):
                if not word.strip():
                    continue
                if text.lower() in word.lower():
                    conf = int(ocr_data["conf"][i]) / 100.0 if ocr_data["conf"][i] != "-1" else 0.5
                    if conf >= config.ocr_confidence_threshold:
                        x = ocr_data["left"][i]
                        y = ocr_data["top"][i]
                        w = ocr_data["width"][i]
                        h = ocr_data["height"][i]
                        return Element(
                            role="unknown",
                            name=word,
                            bbox=BoundingBox(x, y, w, h),
                            confidence=conf,
                        )

            time.sleep(0.2)

        return None

    def find_by_template(self, template_path: str, threshold: float = 0.8, timeout: float = 10.0) -> Optional[Element]:
        """Find a UI element by image template matching."""
        if not self._cv_available:
            raise BackendNotAvailable("visual", "OpenCV not installed. Install: pip install opencv-python")

        template = self._cv2.imread(template_path)
        if template is None:
            raise ElementNotFound(template_path, ["visual"])

        deadline = time.time() + timeout
        while time.time() < deadline:
            from hermes_gui.capture.screen import capture_screenshot
            screenshot = capture_screenshot()
            screen_np = self._cv2.cvtColor(screenshot.image.convert("RGB"), self._cv2.COLOR_RGB2BGR)

            result = self._cv2.matchTemplate(screen_np, template, self._cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = self._cv2.minMaxLoc(result)

            if max_val >= threshold:
                h, w = template.shape[:2]
                return Element(
                    role="template_match",
                    name=template_path,
                    bbox=BoundingBox(max_loc[0], max_loc[1], w, h),
                    confidence=float(max_val),
                )

            time.sleep(0.2)

        return None
