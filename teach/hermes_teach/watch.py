"""Poll the triggers of every workflow in the library and run the ones that fire.

``hermes-teach workflow watch --once`` is meant for cron / systemd timers /
Hermes' own scheduler; without ``--once`` it loops every ``interval``
seconds. Trigger state is persisted per workflow so an event is handled once.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from hermes_teach.secrets import SecretStore
from hermes_teach.triggers import EmailSource, Trigger, TriggerError, TriggerState, poll_files, schedule_due
from hermes_teach.workflow import Library, WfResult, Workflow

Runner = Callable[[Workflow, dict[str, Any]], WfResult]


def email_source(trig: Trigger, wf: Workflow, secrets_override: str | None = None) -> EmailSource:
    cfg = trig.config
    host = cfg.get("host") or os.environ.get("HERMES_TEACH_IMAP_HOST")
    if not host:
        raise TriggerError(f"workflow {wf.name}: email trigger needs 'host' (or HERMES_TEACH_IMAP_HOST)")
    cred = cfg.get("credential")
    store = SecretStore(wf.credentials, override=secrets_override)
    user = cfg.get("user") or os.environ.get("HERMES_TEACH_IMAP_USER")
    if not user and cred:
        user = store.lookup(cred, "username")
    if not user:
        raise TriggerError(f"workflow {wf.name}: email trigger needs 'user' or a credential with a username")

    def password() -> str:
        if cred:
            return store.lookup(cred, "password")
        pw = os.environ.get("HERMES_TEACH_IMAP_PASSWORD")
        if not pw:
            raise TriggerError(f"workflow {wf.name}: email trigger needs 'credential' or HERMES_TEACH_IMAP_PASSWORD")
        return pw

    return EmailSource(str(host), str(user), password, port=int(cfg.get("port", 993)), ssl=bool(cfg.get("ssl", True)),
                       folder=str(cfg.get("folder", "INBOX")), mark_seen=bool(cfg.get("mark_seen", False)))


def poll_workflow(wf: Workflow, state: TriggerState, *, now: float | None = None,
                  email_factory: Callable[[Trigger, Workflow], EmailSource] | None = None,
                  secrets_override: str | None = None) -> list[tuple[Trigger, dict[str, Any]]]:
    """Payloads of all triggers of ``wf`` that fired since the last poll (state is updated)."""
    now = now or time.time()
    fired: list[tuple[Trigger, dict[str, Any]]] = []
    for i, trig in enumerate(wf.on):
        key = f"{trig.kind}:{i}"
        if trig.kind == "email":
            src = (email_factory or (lambda t, w: email_source(t, w, secrets_override)))(trig, wf)
            msgs, last = src.poll(int(state.get(key, 0) or 0))
            state.set(key, last)
            fired += [(trig, m) for m in msgs if trig.matches(m)]
        elif trig.kind == "file":
            d = trig.config.get("dir") or trig.config.get("path") or "."
            new, current = poll_files(d, str(trig.config.get("glob", "*")), set(state.get(key, []) or []),
                                      settle=float(trig.config.get("settle", 2.0)))
            state.set(key, sorted(current))
            fired += [(trig, p) for p in new if trig.matches(p)]
        elif trig.kind == "schedule":
            last = float(state.get(key, 0) or 0)
            if schedule_due(trig.config.get("every", "1d"), last, now):
                state.set(key, now)
                if last:          # first poll only arms the schedule
                    fired.append((trig, {"kind": "schedule", "time": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                                                   time.localtime(now))}))
    return fired


def watch_once(library: Library, run: Runner, state_dir: str | Path, *, log: Callable[[str], None] = print,
               email_factory: Callable[[Trigger, Workflow], EmailSource] | None = None,
               secrets_override: str | None = None) -> list[WfResult]:
    results: list[WfResult] = []
    for path in library.workflows():
        try:
            wf = Workflow.load(path)
        except Exception as e:  # noqa: BLE001 - one broken file must not stop the others
            log(f"skip {path}: {e}")
            continue
        if not any(t.kind in ("email", "file", "schedule") for t in wf.on):
            continue
        state = TriggerState(Path(state_dir) / f"{wf.name}.json")
        try:
            fired = poll_workflow(wf, state, email_factory=email_factory, secrets_override=secrets_override)
        except TriggerError as e:
            log(f"{wf.name}: {e}")
            continue
        for trig, payload in fired:
            log(f"{wf.name}: {trig.kind} trigger fired ({payload.get('subject') or payload.get('name') or ''})")
            results.append(run(wf, payload))
    return results


def watch(library: Library, run: Runner, state_dir: str | Path, *, interval: float = 60, once: bool = False,
           log: Callable[[str], None] = print, **kw: Any) -> None:
    while True:
        watch_once(library, run, state_dir, log=log, **kw)
        if once:
            return
        time.sleep(interval)
