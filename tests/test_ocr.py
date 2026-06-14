"""Tests for hermes_gui OCR layer (Tesseract)."""

import pytest
from hermes_gui.types import TextBlock


class TestTesseractOCR:
    """Tesseract OCR wrapper tests."""

    @pytest.mark.smoke
    def test_ocr_screenshot(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.ocr.tesseract import ocr_screenshot
        screenshot = capture_screenshot()
        blocks = ocr_screenshot(screenshot)
        assert isinstance(blocks, list)
        for block in blocks:
            assert isinstance(block, TextBlock)
            assert isinstance(block.text, str)
            assert block.confidence >= 0.0

    def test_ocr_with_language(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.ocr.tesseract import ocr_screenshot
        screenshot = capture_screenshot()
        blocks = ocr_screenshot(screenshot, language="eng")
        assert isinstance(blocks, list)

    def test_ocr_region(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.ocr.tesseract import ocr_region
        screenshot = capture_screenshot()
        blocks = ocr_region(screenshot, 0, 0, 100, 100)
        assert isinstance(blocks, list)

    def test_ocr_empty_region(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.ocr.tesseract import ocr_region
        screenshot = capture_screenshot()
        blocks = ocr_region(screenshot, 0, 0, 1, 1)
        assert isinstance(blocks, list)
        assert len(blocks) == 0  # 1x1 pixel has no text
