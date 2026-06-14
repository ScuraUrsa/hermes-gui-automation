"""Hermes GUI Automation — Florence-2 VLM wrapper for UI element detection."""

from typing import Optional

from hermes_gui.config import config
from hermes_gui.errors import VLMFailed
from hermes_gui.types import BoundingBox, Element, Screenshot


def find_by_prompt(prompt: str, screenshot: Screenshot, timeout: float = 15.0) -> Element:
    """Find a UI element by natural language description using Florence-2.

    Args:
        prompt: Description like "the blue Submit button in the bottom right"
        screenshot: Screenshot to analyze
        timeout: Maximum time to wait (unused, model runs synchronously)

    Returns:
        Element with position and description
    """
    try:
        from transformers import AutoProcessor, AutoModelForCausalLM
    except ImportError:
        raise VLMFailed("florence-2", "transformers not installed. pip install transformers torch")

    try:
        model = AutoModelForCausalLM.from_pretrained(
            config.florence_model,
            trust_remote_code=True,
        ).eval().to(config.florence_device)
        processor = AutoProcessor.from_pretrained(
            config.florence_model,
            trust_remote_code=True,
        )

        inputs = processor(
            text=f"<OD>{prompt}",
            images=screenshot.image,
            return_tensors="pt",
        ).to(config.florence_device)

        generated_ids = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=256,
            num_beams=3,
        )
        generated_text = processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

        import re
        bbox_match = re.search(r'<x(\d+)><y(\d+)><x(\d+)><y(\d+)>', generated_text)
        label_match = re.search(r'([^<]+)$', generated_text)

        if bbox_match:
            x1, y1, x2, y2 = map(int, bbox_match.groups())
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
