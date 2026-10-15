"""LLM backends used to generalize recordings and to recover failed steps.

* ``AnthropicLLM`` — Claude via the official ``anthropic`` SDK
  (``pip install anthropic``; credentials from ``ANTHROPIC_API_KEY`` or an
  ``ant auth login`` profile).
* ``CommandLLM`` — any command that reads a prompt on stdin and prints the
  answer, so Hermes can plug in whatever model it already runs
  (``HERMES_TEACH_LLM_CMD="hermes chat --stdin"`` or a local model wrapper).

``from_env()`` picks ``CommandLLM`` if ``HERMES_TEACH_LLM_CMD`` is set,
otherwise ``AnthropicLLM``.
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
from typing import Protocol

DEFAULT_MODEL = "claude-opus-5-5"


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def complete(self, system: str, prompt: str, image_png: bytes | None = None) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str | None = None, effort: str = "high") -> None:
        try:
            import anthropic
        except ImportError:
            raise LLMError("pip install anthropic (or set HERMES_TEACH_LLM_CMD)") from None
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("HERMES_TEACH_MODEL", DEFAULT_MODEL)
        self.effort = effort

    def complete(self, system: str, prompt: str, image_png: bytes | None = None) -> str:
        content: list[dict] = []
        if image_png is not None:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.b64encode(image_png).decode()}})
        content.append({"type": "text", "text": prompt})
        try:
            with self.client.beta.messages.stream(
                model=self.model, max_tokens=32000, system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": self.effort},
                # on a policy decline, let the API retry on a fallback model
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            ) as stream:
                msg = stream.get_final_message()
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from None
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"cannot reach Claude API: {e}") from None
        if msg.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        return "".join(b.text for b in msg.content if b.type == "text")


class CommandLLM:
    def __init__(self, command: str, timeout: int = 600) -> None:
        self.command = command
        self.timeout = timeout

    def complete(self, system: str, prompt: str, image_png: bytes | None = None) -> str:
        full = f"{system}\n\n{prompt}"
        env = dict(os.environ)
        if image_png is not None:
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, "wb") as f:
                f.write(image_png)
            env["HERMES_TEACH_IMAGE"] = path
        res = subprocess.run(shlex.split(self.command, posix=os.name != "nt"), input=full,
                             capture_output=True, text=True, timeout=self.timeout, env=env)
        if res.returncode != 0:
            raise LLMError(f"LLM command failed: {res.stderr.strip()[:300]}")
        return res.stdout


def from_env() -> LLM:
    cmd = os.environ.get("HERMES_TEACH_LLM_CMD")
    if cmd:
        return CommandLLM(cmd)
    return AnthropicLLM()
