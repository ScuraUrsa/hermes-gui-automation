"""Tests for hermes_gui input layer (mouse, keyboard, clipboard)."""

import pytest


class TestMouse:
    """Mouse input tests via xdotool."""

    @pytest.mark.smoke
    def test_move(self, display):
        from hermes_gui.input.mouse import move
        move(100, 100)

    @pytest.mark.smoke
    def test_click(self, display):
        from hermes_gui.input.mouse import click
        click(10, 10)

    def test_double_click(self, display):
        from hermes_gui.input.mouse import double_click
        double_click(10, 10)

    def test_right_click(self, display):
        from hermes_gui.input.mouse import right_click
        right_click(10, 10)

    def test_drag(self, display):
        from hermes_gui.input.mouse import drag
        drag(100, 100, 200, 200)

    def test_get_position(self, display):
        from hermes_gui.input.mouse import get_position
        x, y = get_position()
        assert isinstance(x, int)
        assert isinstance(y, int)


class TestKeyboard:
    """Keyboard input tests via xdotool."""

    @pytest.mark.smoke
    def test_type_text(self, display):
        from hermes_gui.input.keyboard import type_text
        type_text("test")

    @pytest.mark.smoke
    def test_press_key(self, display):
        from hermes_gui.input.keyboard import press_key
        press_key("Escape")

    def test_hotkey(self, display):
        from hermes_gui.input.keyboard import hotkey
        hotkey("ctrl", "a")


class TestClipboard:
    """Clipboard tests via xclip."""

    @pytest.mark.smoke
    def test_get_clipboard(self, display):
        from hermes_gui.input.clipboard import get_clipboard_text
        text = get_clipboard_text()
        assert isinstance(text, str)

    def test_set_and_get(self, display):
        from hermes_gui.input.clipboard import set_clipboard_text, get_clipboard_text
        set_clipboard_text("test123")
        text = get_clipboard_text()
        assert "test123" in text
