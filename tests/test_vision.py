"""Tests for hermes_gui vision layer (Florence-2, template matching)."""

import pytest
from hermes_gui.errors import VLMFailed, ElementNotFound


class TestFlorenceVLM:
    """Florence-2 VLM wrapper tests."""

    @pytest.mark.smoke
    def test_import(self):
        from hermes_gui.vision.florence import find_by_prompt
        assert find_by_prompt is not None

    @pytest.mark.vlm
    def test_find_by_prompt_requires_model(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.vision.florence import find_by_prompt
        screenshot = capture_screenshot()
        try:
            element = find_by_prompt("a button", screenshot, timeout=5.0)
            assert element is not None
        except VLMFailed:
            pytest.skip("Florence-2 model not installed")


class TestTemplateMatching:
    """OpenCV template matching tests."""

    @pytest.mark.smoke
    def test_import(self):
        from hermes_gui.vision.templates import match_template, match_all_templates
        assert match_template is not None
        assert match_all_templates is not None

    def test_match_nonexistent_template(self, display):
        from hermes_gui.capture.screen import capture_screenshot
        from hermes_gui.vision.templates import match_template
        screenshot = capture_screenshot()
        try:
            result = match_template("/tmp/nonexistent_template.png", screenshot)
            assert result is None
        except ElementNotFound:
            pass  # Expected — template file doesn't exist
