"""Tests for hermes_gui backends."""

import pytest
from hermes_gui.errors import BackendNotAvailable


class TestATSPIBackend:
    """AT-SPI2 backend tests."""

    @pytest.mark.smoke
    def test_backend_import(self):
        from hermes_gui.backends.atspi import ATSPIBackend
        backend = ATSPIBackend()
        assert backend is not None

    def test_find_element_nonexistent(self):
        from hermes_gui.backends.atspi import ATSPIBackend
        backend = ATSPIBackend()
        if backend._available:
            result = backend.find_element("XYZZY_NONEXISTENT_12345", timeout=1.0)
            assert result is None


class TestVisualBackend:
    """Visual (OCR) backend tests."""

    @pytest.mark.smoke
    def test_backend_import(self):
        from hermes_gui.backends.visual import VisualBackend
        backend = VisualBackend()
        assert backend is not None

    def test_find_element_nonexistent(self):
        from hermes_gui.backends.visual import VisualBackend
        backend = VisualBackend()
        if backend._ocr_available:
            result = backend.find_element("XYZZY_NONEXISTENT_12345", timeout=1.0)
            assert result is None


class TestVLMBackend:
    """VLM backend tests."""

    @pytest.mark.smoke
    def test_backend_import(self):
        from hermes_gui.backends.vlm import VLMBackend
        backend = VLMBackend()
        assert backend is not None

    @pytest.mark.vlm
    def test_find_by_prompt_requires_model(self):
        from hermes_gui.backends.vlm import VLMBackend
        backend = VLMBackend()
        if not backend._florence_available:
            pytest.skip("Florence-2 model not installed")


class TestBrowserBackend:
    """Browser backend tests."""

    @pytest.mark.smoke
    def test_backend_import(self):
        from hermes_gui.backends.browser import BrowserBackend
        backend = BrowserBackend()
        assert backend is not None

    @pytest.mark.browser
    def test_navigate_requires_playwright(self):
        from hermes_gui.backends.browser import BrowserBackend
        backend = BrowserBackend()
        if not backend._available:
            pytest.skip("Playwright not installed")
