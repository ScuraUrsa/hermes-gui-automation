"""Hermes GUI Automation — VLM backend (Florence-2 + OmniParser).

Uses vision-language models to understand UI screenshots and find elements
by natural language description. Handles ambiguous cases where AT-SPI2
and OCR cannot resolve the target.
"""

from typing import Optional

from hermes_gui.config import config
from hermes_gui.errors import BackendNotAvailable, VLMFailed
from hermes_gui.types import BoundingBox, Element


class VLMBackend:
    """Backend using Vision-Language Models for intelligent UI interaction."""

    def __init__(self):
        self._florence_available = False
        self._florence_model = None
        self._florence_processor = None
        try:
            from transformers import AutoProcessor, AutoModelForCausalLM
            self._AutoProcessor = AutoProcessor
            self._AutoModelForCausalLM = AutoModelForCausalLM
            self._florence_available = True
        except ImportError:
            pass

    def _load_florence(self):
        """Lazy-load Florence-2 model."""
        if self._florence_model is not None:
            return
        if not self._florence_available:
            raise BackendNotAvailable("vlm", "transformers not installed. Install: pip install transformers torch")
        try:
            self._florence_model = self._AutoModelForCausalLM.from_pretrained(
                config.florence_model,
                trust_remote_code=True,
            ).eval().to(config.florence_device)
            self._florence_processor = self._AutoProcessor.from_pretrained(
                config.florence_model,
                trust_remote_code=True,
            )
        except Exception as e:
            raise VLMFailed(config.florence_model, str(e))

    def find_element(self, text: str, timeout: float = 10.0) -> Optional[Element]:
        """Find element by text using VLM. Delegates to find_by_prompt."""
        return self.find_by_prompt(f"Find the UI element labeled '{text}'", timeout)

    def find_by_prompt(self, prompt: str, timeout: float = 15.0) -> Element:
        """Find a UI element by natural language description.

        Args:
            prompt: Description like "the blue Submit button in the bottom right"
            timeout: Maximum time to wait

        Returns:
            Element with position and description
        """
        self._load_florence()

        from hermes_gui.capture.screen import capture_screenshot
        screenshot = capture_screenshot()

        try:
            inputs = self._florence_processor(
                text=f"<OD>{prompt}",
                images=screenshot.image,
                return_tensors="pt",
            ).to(config.florence_device)

            generated_ids = self._florence_model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=256,
                num_beams=3,
            )
            generated_text = self._florence_processor.batch_decode(
                generated_ids, skip_special_tokens=True
            )[0]

            # Parse Florence-2 output for bounding box
            # Format: "<OD>region1<x1><y1><x2><y2><label>"
            import re
            bbox_match = re.search(r'<x(\d+)><y(\d+)><x(\d+)><y(\d+)>', generated_text)
            label_match = re.search(r'([^<]+)$', generated_text)

            if bbox_match:
                x1, y1, x2, y2 = map(int, bbox_match.groups())
                # Normalize from 0-999 to actual pixel coordinates
                x1 = int(x1 / 999 * screenshot.width)
                y1 = int(y1 / 999 * screenshot.height)
                x2 = int(x2 / 999 * screenshot.width)
                y2 = int(y2 / 999 * screenshot.height)
                bbox = BoundingBox(x1, y1, x2 - x1, y2 - y1)
            else:
                bbox = BoundingBox(0, 0, 0, 0)

            label = label_match.group(0).strip() if label_match else prompt

            return Element(
                role="vlm_detected",
                name=label,
                description=generated_text,
                bbox=bbox,
                confidence=0.85,
            )

        except Exception as e:
            raise VLMFailed(config.florence_model, str(e))
