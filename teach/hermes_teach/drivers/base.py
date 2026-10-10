"""Driver interface and a dry-run driver used in tests and previews."""

from __future__ import annotations

from typing import Any, Protocol

from hermes_teach.events import Target


class DriverError(RuntimeError):
    pass


class Driver(Protocol):
    def click(self, target: Target, button: str = "left", count: int = 1) -> None: ...
    def type_text(self, text: str, target: Target | None = None) -> None: ...
    def press(self, keys: list[str]) -> None: ...
    def scroll(self, target: Target, dx: int, dy: int) -> None: ...
    def drag(self, target: Target, dx: int, dy: int, button: str = "left") -> None: ...
    def focus(self, target: Target, timeout: float = 10.0) -> None: ...
    def launch(self, command: str) -> None: ...
    def active_window_title(self) -> str: ...
    def close(self) -> None: ...


class DryRunDriver:
    """Records what would happen. Typed secrets are stored redacted."""

    def __init__(self, window_title: str = "") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._title = window_title
        self.secret_values: list[str] = []

    def _log(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))

    def click(self, target: Target, button: str = "left", count: int = 1) -> None:
        self._log("click", target=target.describe(), button=button, count=count)

    def type_text(self, text: str, target: Target | None = None) -> None:
        for s in self.secret_values:
            if s:
                text = text.replace(s, "***")
        self._log("type", text=text)

    def press(self, keys: list[str]) -> None:
        self._log("press", keys="+".join(keys))

    def scroll(self, target: Target, dx: int, dy: int) -> None:
        self._log("scroll", dx=dx, dy=dy)

    def drag(self, target: Target, dx: int, dy: int, button: str = "left") -> None:
        self._log("drag", target=target.describe(), dx=dx, dy=dy)

    def focus(self, target: Target, timeout: float = 10.0) -> None:
        self._title = target.window_title
        self._log("focus", window=target.window_title)

    def launch(self, command: str) -> None:
        self._log("launch", command=command)

    def active_window_title(self) -> str:
        return self._title

    def close(self) -> None:
        return None

    # browser ops, so a dry run can preview mixed procedures
    def browser(self, op: str, target: Target, value: str = "") -> None:
        for s in self.secret_values:
            if s:
                value = value.replace(s, "***")
        self._log(op, selector=target.selector or target.url, value=value)
