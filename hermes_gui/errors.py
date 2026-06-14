"""Hermes GUI Automation — custom exceptions."""


class GUIError(Exception):
    """Base exception for all GUI automation errors."""
    pass


class ElementNotFound(GUIError):
    """Element could not be found by any backend."""
    def __init__(self, query: str, backends_tried: list[str]):
        self.query = query
        self.backends_tried = backends_tried
        super().__init__(
            f"Element '{query}' not found. Backends tried: {', '.join(backends_tried)}"
        )


class OCRFailed(GUIError):
    """OCR engine failed to process the screenshot."""
    def __init__(self, engine: str, reason: str):
        self.engine = engine
        self.reason = reason
        super().__init__(f"OCR failed ({engine}): {reason}")


class VLMFailed(GUIError):
    """VLM model failed to process the screenshot."""
    def __init__(self, model: str, reason: str):
        self.model = model
        self.reason = reason
        super().__init__(f"VLM failed ({model}): {reason}")


class WindowNotFound(GUIError):
    """Window with specified title/pid not found."""
    def __init__(self, query: str):
        self.query = query
        super().__init__(f"Window not found: '{query}'")


class DisplayError(GUIError):
    """Display server (Xvfb/X11) not accessible."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Display error: {reason}")


class InputError(GUIError):
    """Mouse/keyboard input injection failed."""
    def __init__(self, tool: str, reason: str):
        self.tool = tool
        self.reason = reason
        super().__init__(f"Input error ({tool}): {reason}")


class TimeoutError(GUIError):
    """Operation timed out waiting for condition."""
    def __init__(self, condition: str, timeout: float):
        self.condition = condition
        self.timeout = timeout
        super().__init__(f"Timeout after {timeout}s waiting for: {condition}")


class ConcurrencyError(GUIError):
    """Another GUI operation is already in progress."""
    def __init__(self):
        super().__init__("Another GUI operation is in progress. Only one operation at a time.")


class BackendNotAvailable(GUIError):
    """Requested backend is not installed or configured."""
    def __init__(self, backend: str, reason: str):
        self.backend = backend
        self.reason = reason
        super().__init__(f"Backend '{backend}' not available: {reason}")
