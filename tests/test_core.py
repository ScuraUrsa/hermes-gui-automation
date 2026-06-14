"""Tests for hermes_gui core orchestration."""

import pytest
from hermes_gui.core import (
    gui_screenshot, gui_ocr, gui_find, gui_click, gui_type,
    gui_list_windows, gui_focus_window, gui_get_active_window,
    gui_close_window, gui_copy, gui_paste, gui_get_clipboard,
    gui_wait_for_text, gui_wait_for_window, gui_fill_form,
    gui_launch, gui_hotkey, gui_press, gui_move, gui_drag,
    gui_double_click, gui_right_click, gui_find_by_prompt,
    gui_browser_navigate, gui_browser_click, gui_browser_type, gui_browser_snapshot,
)
from hermes_gui.errors import ElementNotFound, ConcurrencyError, TimeoutError
from hermes_gui.types import BoundingBox, Element, Screenshot, TextBlock, Window


class TestScreenshot:
    """Screen capture tests."""

    @pytest.mark.smoke
    def test_full_screenshot(self, display):
        screenshot = gui_screenshot()
        assert isinstance(screenshot, Screenshot)
        assert screenshot.width > 0
        assert screenshot.height > 0
        assert screenshot.image is not None

    @pytest.mark.smoke
    def test_region_screenshot(self, display):
        screenshot = gui_screenshot(region=(0, 0, 100, 100))
        assert screenshot.width == 100
        assert screenshot.height == 100

    def test_screenshot_metadata(self, display):
        screenshot = gui_screenshot()
        assert screenshot.timestamp > 0
        assert screenshot.region is None  # Full screen has no region


class TestOCR:
    """OCR tests."""

    @pytest.mark.smoke
    def test_ocr_returns_blocks(self, display):
        screenshot = gui_screenshot()
        blocks = gui_ocr(screenshot)
        assert isinstance(blocks, list)
        for block in blocks:
            assert isinstance(block, TextBlock)
            assert isinstance(block.text, str)
            assert isinstance(block.bbox, BoundingBox)

    def test_ocr_with_language(self, display):
        screenshot = gui_screenshot()
        blocks = gui_ocr(screenshot, language="eng")
        assert isinstance(blocks, list)


class TestElementFinding:
    """Element finding tests."""

    @pytest.mark.smoke
    def test_find_nonexistent_element(self, display):
        with pytest.raises(ElementNotFound):
            gui_find("XYZZY_NONEXISTENT_TEXT_12345", timeout=2.0)

    def test_find_by_prompt(self, display):
        with pytest.raises(Exception):  # VLM may not be installed
            gui_find_by_prompt("a button", timeout=2.0)


class TestMouse:
    """Mouse control tests."""

    @pytest.mark.smoke
    def test_move_mouse(self, display):
        gui_move(100, 100)

    @pytest.mark.smoke
    def test_click_coordinates(self, display):
        gui_click(x=10, y=10)

    def test_double_click(self, display):
        gui_double_click(x=10, y=10)

    def test_right_click(self, display):
        gui_right_click(x=10, y=10)

    def test_drag(self, display):
        gui_drag((100, 100), (200, 200))


class TestKeyboard:
    """Keyboard input tests."""

    @pytest.mark.smoke
    def test_type_text(self, display):
        gui_type("test")

    @pytest.mark.smoke
    def test_press_key(self, display):
        gui_press("Escape")

    def test_hotkey(self, display):
        gui_hotkey("ctrl", "a")


class TestWindowManagement:
    """Window management tests."""

    @pytest.mark.smoke
    def test_list_windows(self, display):
        windows = gui_list_windows()
        assert isinstance(windows, list)
        for w in windows:
            assert isinstance(w, Window)
            assert isinstance(w.title, str)

    def test_get_active_window(self, display):
        window = gui_get_active_window()
        assert isinstance(window, Window)

    def test_focus_nonexistent_window(self, display):
        with pytest.raises(Exception):
            gui_focus_window("XYZZY_NONEXISTENT_WINDOW_12345")


class TestClipboard:
    """Clipboard tests."""

    @pytest.mark.smoke
    def test_get_clipboard(self, display):
        text = gui_get_clipboard()
        assert isinstance(text, str)

    def test_copy_paste_cycle(self, display):
        gui_type("test_clipboard_content")
        gui_hotkey("ctrl", "a")
        gui_copy()
        text = gui_get_clipboard()
        assert isinstance(text, str)


class TestWaitConditions:
    """Wait condition tests."""

    def test_wait_for_text_timeout(self, display):
        with pytest.raises(TimeoutError):
            gui_wait_for_text("XYZZY_NONEXISTENT_12345", timeout=2.0)

    def test_wait_for_window_timeout(self, display):
        with pytest.raises(TimeoutError):
            gui_wait_for_window("XYZZY_NONEXISTENT_WINDOW_12345", timeout=2.0)


class TestConcurrency:
    """Concurrency control tests."""

    def test_concurrent_ops_blocked(self, display):
        import threading
        import time

        def hold_lock():
            from hermes_gui.core import _acquire_lock, _release_lock
            _acquire_lock("test_op")
            time.sleep(1.0)
            _release_lock()

        t = threading.Thread(target=hold_lock)
        t.start()
        time.sleep(0.1)

        with pytest.raises(ConcurrencyError):
            gui_find("test", timeout=0.5)

        t.join()


class TestTypes:
    """Type dataclass tests."""

    def test_bounding_box_center(self):
        bbox = BoundingBox(100, 200, 80, 30)
        assert bbox.center == (140, 215)

    def test_bounding_box_contains(self):
        bbox = BoundingBox(100, 200, 80, 30)
        assert bbox.contains(140, 215)
        assert not bbox.contains(0, 0)

    def test_bounding_box_iou(self):
        a = BoundingBox(0, 0, 100, 100)
        b = BoundingBox(50, 50, 100, 100)
        iou = a.overlap(b)
        assert 0.1 < iou < 0.2

    def test_element_defaults(self):
        elem = Element()
        assert elem.role == ""
        assert elem.confidence == 1.0

    def test_window_defaults(self):
        win = Window()
        assert win.title == ""
        assert win.pid == 0
