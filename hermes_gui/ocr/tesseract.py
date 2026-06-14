"""Hermes GUI Automation — Tesseract OCR wrapper."""

import subprocess
import tempfile
import os

from hermes_gui.config import config
from hermes_gui.errors import OCRFailed
from hermes_gui.types import BoundingBox, Screenshot, TextBlock


def ocr_screenshot(screenshot: Screenshot, language: str = "eng") -> list[TextBlock]:
    """Run Tesseract OCR on a screenshot and return text blocks with bounding boxes.

    Args:
        screenshot: Screenshot to OCR.
        language: Tesseract language code (default: eng).

    Returns:
        List of TextBlock objects.
    """
    try:
        import pytesseract
    except ImportError:
        raise OCRFailed("tesseract", "pytesseract not installed. pip install pytesseract")

    try:
        data = pytesseract.image_to_data(
            screenshot.image,
            lang=language,
            output_type=pytesseract.Output.DICT,
            config=f'--tessdata-dir "{config.tesseract_data_dir}"',
        )
    except Exception as e:
        raise OCRFailed("tesseract", str(e))

    blocks = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        conf_str = data["conf"][i]
        conf = float(conf_str) / 100.0 if conf_str != "-1" else 0.5
        bbox = BoundingBox(
            data["left"][i],
            data["top"][i],
            data["width"][i],
            data["height"][i],
        )
        blocks.append(TextBlock(text=text, bbox=bbox, confidence=conf))

    return blocks


def ocr_region(screenshot: Screenshot, x: int, y: int, w: int, h: int, language: str = "eng") -> list[TextBlock]:
    """OCR only a specific region of a screenshot."""
    cropped = screenshot.image.crop((x, y, x + w, y + h))
    region_screenshot = Screenshot(
        image=cropped,
        width=w,
        height=h,
        timestamp=screenshot.timestamp,
    )
    blocks = ocr_screenshot(region_screenshot, language)
    # Adjust coordinates back to full-screen space
    for block in blocks:
        block.bbox.x += x
        block.bbox.y += y
    return blocks
