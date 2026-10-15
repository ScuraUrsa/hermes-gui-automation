"""LLM-assisted recovery when a recorded target cannot be found.

When the window layout changed (moved button, different resolution, renamed
control) the runner asks the LLM to locate the target on a screenshot and
clicks there. Every recovery is counted in the run result; a procedure that
needs recoveries is not "stable" and should be re-recorded or fixed before it
is promoted to a script.
"""

from __future__ import annotations

import json
import re
from typing import Any

from hermes_teach.llm import LLM
from hermes_teach.procedure import ProcStep

SYSTEM = ("You locate UI elements on screenshots for a desktop automation agent. "
          'Answer with JSON only: {"x": <int>, "y": <int>} in screenshot pixels, '
          'or {"x": null, "y": null} if the element is not visible.')


class VisionRecovery:
    def __init__(self, llm: LLM, driver: Any) -> None:
        self.llm = llm
        self.driver = driver

    def _screenshot(self) -> tuple[bytes, int, int]:
        import mss
        import mss.tools
        with mss.mss() as sct:
            mon = sct.monitors[0]
            img = sct.grab(mon)
            return mss.tools.to_png(img.rgb, img.size), mon["left"], mon["top"]

    def __call__(self, step: ProcStep, error: Exception) -> bool:
        if step.action != "click":
            return False
        png, left, top = self._screenshot()
        reply = self.llm.complete(SYSTEM, f"Find: {step.target.describe()}. "
                                  f"Context: the previous attempt failed with '{error}'.", image_png=png)
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            return False
        pos = json.loads(m.group(0))
        if pos.get("x") is None:
            return False
        from hermes_teach.events import Target
        self.driver.click(Target(x=int(pos["x"]) + left, y=int(pos["y"]) + top), step.button, step.count)
        return True
