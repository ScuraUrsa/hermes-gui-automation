"""Hermes GUI Automation — geometry utilities."""

from hermes_gui.types import BoundingBox


def intersection(a: BoundingBox, b: BoundingBox) -> BoundingBox | None:
    """Compute intersection of two bounding boxes."""
    xi = max(a.x, b.x)
    yi = max(a.y, b.y)
    xa = min(a.x + a.width, b.x + b.width)
    ya = min(a.y + a.height, b.y + b.height)
    if xi >= xa or yi >= ya:
        return None
    return BoundingBox(xi, yi, xa - xi, ya - yi)


def union(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    """Compute union bounding box containing both."""
    x = min(a.x, b.x)
    y = min(a.y, b.y)
    w = max(a.x + a.width, b.x + b.width) - x
    h = max(a.y + a.height, b.y + b.height) - y
    return BoundingBox(x, y, w, h)


def iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection over Union."""
    inter = intersection(a, b)
    if inter is None:
        return 0.0
    inter_area = inter.area
    union_area = a.area + b.area - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def distance(a: BoundingBox, b: BoundingBox) -> float:
    """Euclidean distance between centers of two boxes."""
    ca = a.center
    cb = b.center
    return ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5


def expand(bbox: BoundingBox, padding: int) -> BoundingBox:
    """Expand a bounding box by padding on all sides."""
    return BoundingBox(
        max(0, bbox.x - padding),
        max(0, bbox.y - padding),
        bbox.width + 2 * padding,
        bbox.height + 2 * padding,
    )


def contains_point(bbox: BoundingBox, x: int, y: int) -> bool:
    """Check if a point is inside a bounding box."""
    return bbox.x <= x <= bbox.x + bbox.width and bbox.y <= y <= bbox.y + bbox.height
