"""Hermes GUI Automation — type definitions."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BoundingBox:
    """Rectangle on screen."""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    def overlap(self, other: "BoundingBox") -> float:
        """Intersection over Union (IoU) with another box."""
        xi = max(self.x, other.x)
        yi = max(self.y, other.y)
        xa = min(self.x + self.width, other.x + other.width)
        ya = min(self.y + self.height, other.y + other.height)
        if xi >= xa or yi >= ya:
            return 0.0
        inter = (xa - xi) * (ya - yi)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass
class Element:
    """A UI element found on screen."""
    role: str = ""                # AT-SPI2 role: push_button, text_field, label, etc.
    name: str = ""                # Accessible name / visible text
    description: str = ""         # Additional description (VLM-generated)
    bbox: BoundingBox = field(default_factory=lambda: BoundingBox(0, 0, 0, 0))
    confidence: float = 1.0       # 0.0-1.0 confidence in this element
    backend: str = ""             # Which backend found it: atspi, visual, vlm, browser
    properties: dict = field(default_factory=dict)  # Extra backend-specific properties


@dataclass
class TextBlock:
    """A block of text extracted by OCR."""
    text: str
    bbox: BoundingBox
    confidence: float = 0.0       # OCR confidence 0-100
    font_size: int = 0            # Estimated font size in pixels


@dataclass
class Window:
    """A desktop window."""
    id: str = ""                  # Window ID (X11 hex or Wayland handle)
    title: str = ""
    pid: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    desktop: int = 0              # Virtual desktop number
    is_active: bool = False
    class_name: str = ""          # WM_CLASS


@dataclass
class Screenshot:
    """A captured screenshot with metadata."""
    image: "Image" = None         # PIL Image object
    width: int = 0
    height: int = 0
    timestamp: float = 0.0
    region: Optional[BoundingBox] = None  # If partial capture
    window_title: Optional[str] = None    # If window-specific capture
