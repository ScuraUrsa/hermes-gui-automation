"""Raw recorded events and normalized steps.

A recording is a JSONL file: one ``RawEvent`` per line. The recorder writes
it as it goes, so a crash never loses more than the last event. The
normalizer (``hermes_teach.normalize``) turns raw events into ``Step``s,
which are what procedures and the LLM work with.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# Raw event kinds written by recorders.
MOUSE_DOWN = "mouse_down"
MOUSE_UP = "mouse_up"
SCROLL = "scroll"
KEY_DOWN = "key_down"
KEY_UP = "key_up"
WINDOW = "window"          # active window changed
MARK = "mark"              # user annotation / control event (start, stop, privacy on/off)
BROWSER = "browser"        # DOM-level event from the browser recorder

MODIFIERS = ("ctrl", "alt", "shift", "cmd")


@dataclass
class Target:
    """Where an action happened, as precisely as the platform lets us know."""

    x: int | None = None                 # absolute screen coordinates
    y: int | None = None
    window_title: str = ""
    window_class: str = ""                # X11 WM_CLASS / Win32 class name
    process: str = ""                     # executable name, e.g. notepad.exe
    off_x: int | None = None              # offset from the window's top-left corner, px
    off_y: int | None = None
    element_name: str = ""                # accessible name (UIA / AT-SPI)
    element_role: str = ""                # button, check_box, edit, ...
    automation_id: str = ""               # UIA AutomationId (Windows only)
    selector: str = ""                    # CSS/role selector (browser only)
    url: str = ""                         # page URL (browser only)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Target":
        data = data or {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        parts = []
        if self.element_name or self.element_role:
            parts.append(f"{self.element_role or 'element'} '{self.element_name}'")
        if self.selector:
            parts.append(f"selector {self.selector}")
        if self.window_title:
            parts.append(f"in window '{self.window_title}'")
        if not parts and self.x is not None:
            parts.append(f"at ({self.x},{self.y})")
        return " ".join(parts) or "unknown target"


@dataclass
class RawEvent:
    t: float                               # seconds since recording start
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    target: Target | None = None

    def to_json(self) -> str:
        out: dict[str, Any] = {"t": round(self.t, 4), "kind": self.kind, "data": self.data}
        if self.target is not None:
            out["target"] = self.target.to_dict()
        return json.dumps(out, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RawEvent":
        tgt = d.get("target")
        return cls(t=float(d["t"]), kind=d["kind"], data=d.get("data") or {},
                   target=Target.from_dict(tgt) if tgt is not None else None)


@dataclass
class Step:
    """One user-level action: click, type, hotkey, key, scroll, focus, browser op."""

    action: str
    target: Target = field(default_factory=Target)
    text: str = ""                 # for type / fill
    keys: list[str] = field(default_factory=list)   # for hotkey / key
    button: str = "left"
    count: int = 1                 # 2 = double click
    dx: int = 0                    # scroll amounts / drag end
    dy: int = 0
    sensitive: bool = False        # text was typed into a password field (masked)
    t: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"action": self.action}
        tgt = self.target.to_dict()
        if tgt:
            d["target"] = tgt
        if self.text:
            d["text"] = self.text
        if self.keys:
            d["keys"] = list(self.keys)
        if self.action in ("click", "drag") and self.button != "left":
            d["button"] = self.button
        if self.count != 1:
            d["count"] = self.count
        if self.dx or self.dy:
            d["dx"], d["dy"] = self.dx, self.dy
        if self.sensitive:
            d["sensitive"] = True
        d["t"] = round(self.t, 3)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(
            action=d["action"], target=Target.from_dict(d.get("target")),
            text=d.get("text", ""), keys=list(d.get("keys", [])),
            button=d.get("button", "left"), count=int(d.get("count", 1)),
            dx=int(d.get("dx", 0)), dy=int(d.get("dy", 0)),
            sensitive=bool(d.get("sensitive", False)), t=float(d.get("t", 0.0)),
        )

    def describe(self) -> str:
        if self.action == "click":
            n = "double-click" if self.count == 2 else f"{self.button}-click"
            return f"{n} {self.target.describe()}"
        if self.action == "type":
            shown = "<secret>" if self.sensitive else repr(self.text)
            return f"type {shown} into {self.target.describe()}"
        if self.action in ("hotkey", "key"):
            return f"press {'+'.join(self.keys)}"
        if self.action == "scroll":
            return f"scroll ({self.dx},{self.dy}) {self.target.describe()}"
        if self.action == "focus":
            return f"switch to window '{self.target.window_title}'"
        if self.action == "drag":
            return f"drag from {self.target.describe()} by ({self.dx},{self.dy})"
        return f"{self.action} {self.target.describe()} {self.text}".strip()


def write_events(path: str | Path, events: Iterable[RawEvent]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(ev.to_json() + "\n")


def read_events(path: str | Path) -> Iterator[RawEvent]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield RawEvent.from_dict(json.loads(line))
