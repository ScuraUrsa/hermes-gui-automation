"""Execute a procedure with parameters, secrets, confirmations and metrics."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from hermes_teach import platform as plat_mod
from hermes_teach.drivers.base import DriverError
from hermes_teach.metrics import Metrics
from hermes_teach.procedure import Procedure, ProcStep, evaluate, render
from hermes_teach.secrets import SecretError, SecretStore

ConfirmFn = Callable[[str], bool]


@dataclass
class RunResult:
    status: str                       # ok | failed | cancelled
    executed: list[str] = field(default_factory=list)   # human-readable, secrets redacted
    skipped: list[int] = field(default_factory=list)    # step numbers skipped by `when`
    failed_step: int | None = None
    error: str = ""
    duration: float = 0.0
    run_id: int | None = None


def _deny(_: str) -> bool:
    return False


class Runner:
    def __init__(self, procedure: Procedure, *, desktop: Any = None, browser_factory: Callable[[], Any] | None = None,
                 secrets: SecretStore | None = None, confirm: ConfirmFn = _deny,
                 metrics: Metrics | None = None, expect_timeout: float = 10.0,
                 log: Callable[[str], None] | None = None, resolve_secrets: bool = True,
                 recover: Callable[[ProcStep, Exception], bool] | None = None) -> None:
        self.proc = procedure
        self.resolve_secrets = resolve_secrets   # False = dry run, secrets shown as <secret>
        self.desktop = desktop
        self.browser_factory = browser_factory
        self._browser: Any = None
        self.secrets = secrets or SecretStore(procedure.credentials)
        self.confirm = confirm
        self.metrics = metrics
        self.expect_timeout = expect_timeout
        self.log = log or (lambda _m: None)
        self.recover = recover        # e.g. VisionRecovery: let the LLM find a moved button
        self.recovered: list[int] = []

    def plan(self, params: dict[str, Any]) -> list[tuple[int, ProcStep, bool]]:
        """(step number, step, will_run) — what a run with these params would do."""
        values = self.proc.resolve_params(params)
        return [(i, s, (not s.when) or evaluate(s.when, values)) for i, s in enumerate(self.proc.steps, 1)]

    def _browser_driver(self) -> Any:
        if self._browser is None:
            if self.browser_factory is None:
                raise DriverError("procedure has browser steps but no browser driver is configured")
            self._browser = self.browser_factory()
        return self._browser

    def run(self, params: dict[str, Any], mode: str = "replay") -> RunResult:
        started = time.time()
        res = RunResult(status="ok")
        values: dict[str, Any] = {}
        try:
            values = self.proc.resolve_params(params)
            needed = self.proc.used_credentials(values)
            if needed and self.resolve_secrets:
                self.secrets.check_ready(needed)
            if self.proc.requires_confirmation and not self.confirm(
                    f"Run '{self.proc.name}' with {values}?"):
                res.status = "cancelled"
                return res
            for i, step in enumerate(self.proc.steps, 1):
                if step.when and not evaluate(step.when, values):
                    res.skipped.append(i)
                    continue
                res.failed_step = i
                text = render(step.text, values, self.secrets.lookup if self.resolve_secrets else None)
                shown_text = "***" if step.sensitive else text
                shown = self.secrets.redact(f"{i}. {step.action} {step.target.describe()} {shown_text}")
                if step.confirm and not self.confirm(f"Step {shown} — continue?"):
                    res.status = "cancelled"
                    return res
                self.log(shown)
                try:
                    self._execute(step, text, values)
                except DriverError as e:
                    if self.recover is None or not self.recover(step, e):
                        raise
                    self.recovered.append(i)
                self._check_expect(step)
                res.executed.append(shown)
            res.failed_step = None
        except (DriverError, SecretError, Exception) as e:  # noqa: BLE001 - every failure is recorded
            res.status = "failed"
            res.error = self.secrets.redact(f"{type(e).__name__}: {e}")
        finally:
            res.duration = time.time() - started
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self.metrics is not None:
                res.run_id = self.metrics.record(
                    self.proc.name, self.proc.version, res.status, duration=res.duration,
                    failed_step=res.failed_step if res.status == "failed" else None,
                    error=res.error, params=values, mode=mode, started=started)
        return res

    def _execute(self, step: ProcStep, text: str, values: dict[str, Any]) -> None:
        a = step.action
        if a.startswith("browser."):
            tgt = step.target
            if a == "browser.goto":
                tgt = type(tgt)(**{**tgt.__dict__, "url": render(tgt.url, values)})
            drv = self._browser_driver()
            if hasattr(drv, "browser_op"):
                drv.browser_op(a, tgt, text, step.keys)
            else:
                drv.browser(a, tgt, text)
            return
        d = self.desktop
        if d is None:
            raise DriverError("procedure has desktop steps but no desktop driver is configured")
        if a == "click":
            d.click(step.target, step.button, step.count)
        elif a == "type":
            d.type_text(text, step.target)
        elif a in ("key", "hotkey"):
            d.press(step.keys)
        elif a == "scroll":
            d.scroll(step.target, step.dx, step.dy)
        elif a == "drag":
            d.drag(step.target, step.dx, step.dy, step.button)
        elif a == "focus":
            d.focus(step.target, timeout=self.expect_timeout)
        elif a == "launch":
            d.launch(text)
        elif a == "wait":
            time.sleep(step.seconds)
        else:
            raise DriverError(f"unsupported action {a}")

    def _check_expect(self, step: ProcStep) -> None:
        pattern = step.expect.get("window_title")
        if not pattern:
            return
        drv = self._browser if step.action.startswith("browser.") else self.desktop
        deadline = time.time() + float(step.expect.get("timeout", self.expect_timeout))
        title = ""
        while time.time() < deadline:
            title = drv.active_window_title() if drv is not None else ""
            if plat_mod.title_matches(str(pattern), title):
                return
            time.sleep(0.2)
        raise DriverError(f"expected window '{pattern}', got '{title}'")
