"""Tests for hermes_gui capture layer (screenshot, window management)."""

import pytest
from hermes_gui.errors import WindowNotFound
from hermes_gui.types import Screenshot, Window


class TestScreenshot:
    """Screenshot capture tests."""

    @pytest.mark.smoke
    def test_full_screenshot(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        screenshot = capture_screenshot()
        assert isinstance(screenshot, Screenshot)
        assert screenshot.width > 0
        assert screenshot.height > 0
        assert screenshot.image is not None

    def test_region_screenshot(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        screenshot = capture_screenshot(region=(0, 0, 100, 100))
        assert screenshot.width == 100
        assert screenshot.height == 100

    def test_screenshot_metadata(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        screenshot = capture_screenshot()
        assert screenshot.timestamp > 0


class TestWindowManagement:
    """Window management tests."""

    @pytest.mark.smoke
    def test_list_windows(self, display):
        from hermes_gui.capture.window import list_windows
        windows = list_windows()
        assert isinstance(windows, list)
        for w in windows:
            assert isinstance(w, Window)

    @pytest.mark.smoke
    def test_get_active_window(self, display):
        from hermes_gui.capture.window import get_active_window
        window = get_active_window()
        assert isinstance(window, Window)

    def test_focus_nonexistent(self, display):
        from hermes_gui.capture.window import focus_window
        with pytest.raises(WindowNotFound):
            focus_window(title="XYZZY_NONEXISTENT_12345")

    def test_get_geometry_nonexistent(self, display):
        from hermes_gui.capture.window import get_window_geometry
        with pytest.raises(WindowNotFound):
            get_window_geometry("XYZZY_NONEXISTENT_12345")

    def test_close_nonexistent(self, display):
        from hermes_gui.capture.window import close_window
        with pytest.raises(WindowNotFound):
            close_window("XYZZY_NONEXISTENT_12345")
