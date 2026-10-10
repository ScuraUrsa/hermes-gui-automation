"""Turn a raw event stream into user-level steps.

Rules (same on Windows and Linux, since recorders emit canonical key names):

* printable characters typed without Ctrl/Alt/Cmd are merged into one
  ``type`` step until something else happens (click, special key, hotkey,
  window switch); Backspace inside such a run edits the buffer instead of
  being replayed;
* a non-modifier key pressed while Ctrl/Alt/Cmd is held becomes ``hotkey``
  (AltGr characters such as Polish ``ą`` stay text);
* Enter/Tab/Esc/arrows/F-keys become ``key`` steps;
* mouse down+up close together is a ``click``, two quick clicks merge into a
  double click, a long move between down and up is a ``drag``;
* consecutive scroll ticks merge;
* active window changes become ``focus`` steps;
* DOM events from the browser recorder become ``browser.*`` steps, with
  repeated fills of the same field collapsed into the final value.
"""

from __future__ import annotations

import math
from typing import Iterable

from hermes_teach.events import (
    BROWSER,
    KEY_DOWN,
    MARK,
    MODIFIERS,
    MOUSE_DOWN,
    MOUSE_UP,
    SCROLL,
    WINDOW,
    RawEvent,
    Step,
    Target,
)

DOUBLE_CLICK_S = 0.45
DOUBLE_CLICK_PX = 6
DRAG_PX = 12
SCROLL_MERGE_S = 0.8


def _is_text_char(ch: str | None) -> bool:
    return bool(ch) and len(ch) == 1 and (ch.isprintable() or ch == " ")


def normalize(events: Iterable[RawEvent]) -> list[Step]:
    steps: list[Step] = []
    held: set[str] = set()
    buf: list[str] = []
    buf_target: Target | None = None
    buf_t = 0.0
    buf_sensitive = False
    pending_down: RawEvent | None = None
    last_window = ""

    def flush() -> None:
        nonlocal buf, buf_target, buf_sensitive
        if buf:
            steps.append(Step(action="type", target=buf_target or Target(),
                              text="" if buf_sensitive else "".join(buf),
                              sensitive=buf_sensitive, t=buf_t))
        buf, buf_target, buf_sensitive = [], None, False

    for ev in events:
        if ev.kind == MARK:
            continue

        if ev.kind == WINDOW:
            title = ev.target.window_title if ev.target else ""
            if title and title != last_window:
                flush()
                last_window = title
                if steps and steps[-1].action == "focus":
                    steps.pop()          # only the final window of a quick switch matters
                steps.append(Step(action="focus", target=ev.target or Target(), t=ev.t))
            continue

        if ev.kind == KEY_DOWN:
            key = ev.data.get("key", "")
            ch = ev.data.get("char")
            sensitive = bool(ev.data.get("sensitive"))
            if key in MODIFIERS:
                held.add(key)
                continue
            if key == "alt_gr":
                held.add("alt_gr")
                continue
            combo_mods = [m for m in ("ctrl", "alt", "shift", "cmd") if m in held]
            altgr_text = _is_text_char(ch) and (
                "alt_gr" in held or ({"ctrl", "alt"} <= held and not ch.isascii()))
            if (held & {"ctrl", "alt", "cmd"}) and not altgr_text:
                flush()
                name = (ch.lower() if _is_text_char(ch) and ch.isalpha() else key) or (ch or "")
                steps.append(Step(action="hotkey", keys=combo_mods + [name], t=ev.t,
                                  target=ev.target or Target()))
                continue
            if _is_text_char(ch):
                if buf and sensitive != buf_sensitive:
                    flush()
                if not buf:
                    buf_target, buf_t, buf_sensitive = ev.target, ev.t, sensitive
                buf.append(ch)
                continue
            if key == "backspace" and buf:
                buf.pop()
                continue
            flush()
            mods = [m for m in combo_mods if m == "shift"]
            steps.append(Step(action="key", keys=mods + [key], t=ev.t, target=ev.target or Target()))
            continue

        if ev.kind == "key_up":
            key = ev.data.get("key", "")
            held.discard(key)
            continue

        if ev.kind == MOUSE_DOWN:
            flush()
            pending_down = ev
            continue

        if ev.kind == MOUSE_UP:
            down, pending_down = pending_down, None
            if down is None or down.target is None or ev.target is None:
                continue
            button = ev.data.get("button", "left")
            dx = (ev.target.x or 0) - (down.target.x or 0)
            dy = (ev.target.y or 0) - (down.target.y or 0)
            if math.hypot(dx, dy) > DRAG_PX:
                steps.append(Step(action="drag", target=down.target, button=button,
                                  dx=dx, dy=dy, t=down.t))
                continue
            prev = steps[-1] if steps else None
            if (prev is not None and prev.action == "click" and prev.button == button
                    and prev.count == 1 and down.t - prev.t <= DOUBLE_CLICK_S
                    and abs((prev.target.x or 0) - (down.target.x or 0)) <= DOUBLE_CLICK_PX
                    and abs((prev.target.y or 0) - (down.target.y or 0)) <= DOUBLE_CLICK_PX):
                prev.count = 2
                continue
            steps.append(Step(action="click", target=down.target, button=button, t=down.t))
            continue

        if ev.kind == SCROLL:
            flush()
            prev = steps[-1] if steps else None
            sdx, sdy = int(ev.data.get("dx", 0)), int(ev.data.get("dy", 0))
            if (prev is not None and prev.action == "scroll" and ev.t - prev.t <= SCROLL_MERGE_S
                    and ev.target is not None
                    and prev.target.window_title == ev.target.window_title):
                prev.dx += sdx
                prev.dy += sdy
                prev.t = ev.t
                continue
            steps.append(Step(action="scroll", target=ev.target or Target(), dx=sdx, dy=sdy, t=ev.t))
            continue

        if ev.kind == BROWSER:
            flush()
            _browser_step(steps, ev)
            continue

    flush()
    return steps


def _browser_step(steps: list[Step], ev: RawEvent) -> None:
    op = ev.data.get("op", "")
    tgt = ev.target or Target()
    prev = steps[-1] if steps else None
    if op == "fill":
        if prev is not None and prev.action == "browser.fill" and prev.target.selector == tgt.selector:
            prev.text = ev.data.get("value", "")
            prev.sensitive = prev.sensitive or bool(ev.data.get("sensitive"))
            if prev.sensitive:
                prev.text = ""
            return
        sensitive = bool(ev.data.get("sensitive"))
        last = next((s for s in reversed(steps)
                     if s.action == "browser.fill" and s.target.selector == tgt.selector), None)
        if last is not None and (last.sensitive if sensitive else last.text == ev.data.get("value", "")):
            return      # the 'change' event that follows the 'input' events on blur
        steps.append(Step(action="browser.fill", target=tgt, t=ev.t, sensitive=sensitive,
                          text="" if sensitive else ev.data.get("value", "")))
        return
    if op == "navigate":
        if prev is not None and prev.action == "browser.goto" and prev.target.url == tgt.url:
            return
        if prev is not None and prev.action in ("browser.click", "browser.press"):
            return          # navigation caused by the previous action; replay will follow it
        steps.append(Step(action="browser.goto", target=tgt, t=ev.t))
        return
    if op == "press":
        steps.append(Step(action="browser.press", target=tgt, keys=[ev.data.get("key", "")], t=ev.t))
        return
    if op in ("check", "uncheck"):
        steps.append(Step(action=f"browser.{op}", target=tgt, t=ev.t))
        return
    if op == "select":
        steps.append(Step(action="browser.select", target=tgt, text=ev.data.get("value", ""), t=ev.t))
        return
    if op == "click":
        steps.append(Step(action="browser.click", target=tgt, t=ev.t))
