"""hermes-teach command line.

    hermes-teach record --out rec.jsonl            # desktop, Ctrl+Shift+F12 stops
    hermes-teach record-browser https://... --out rec.jsonl
    hermes-teach steps rec.jsonl
    hermes-teach generalize rec.jsonl --name invoice --variations "..." [--llm] --out proc.yaml
    hermes-teach run proc.yaml --param supplier=ACME [--dry-run] [--yes]
    hermes-teach verdict accept|reject
    hermes-teach metrics [name]
    hermes-teach compile proc.yaml [--target playwright|autoit|xdotool]
    hermes-teach export-skill proc.yaml --dir ~/.hermes/skills
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_teach.events import read_events
from hermes_teach.metrics import DEFAULT_STREAK, Metrics
from hermes_teach.normalize import normalize
from hermes_teach.procedure import Procedure, render


def home() -> Path:
    return Path(os.environ.get("HERMES_TEACH_HOME", Path.home() / ".hermes" / "teach"))


def _metrics() -> Metrics:
    return Metrics(home() / "metrics.sqlite")


def _os_name() -> str:
    return "windows" if sys.platform.startswith("win") else "linux"


def _params(pairs: list[str]) -> dict[str, Any]:
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param expects name=value, got '{pair}'")
        k, v = pair.split("=", 1)
        out[k.strip()] = v
    return out


def _ask(q: str) -> bool:
    try:
        return input(f"{q} [y/N] ").strip().lower() in ("y", "yes", "t", "tak")
    except EOFError:
        return False


def cmd_record(a: argparse.Namespace) -> int:
    import time

    from hermes_teach.recorder.desktop import DesktopRecorder
    if a.delay:
        print(f"Recording starts in {a.delay}s...")
        time.sleep(a.delay)
    rec = DesktopRecorder(a.out, screenshots_dir=a.screenshots)
    rec.start()
    print(f"Recording to {a.out}. Ctrl+Shift+F12 stops, Ctrl+Shift+F11 toggles privacy mode.")
    try:
        rec.wait(a.max_seconds or None)
    except KeyboardInterrupt:
        pass
    rec.stop()
    print(f"Saved {rec.count} events.")
    return 0


def cmd_record_browser(a: argparse.Namespace) -> int:
    from hermes_teach.recorder.browser import BrowserRecorder
    rec = BrowserRecorder(a.out, a.url, headless=False, user_data_dir=a.profile)
    rec.start()
    print(f"Recording browser to {a.out}. Close the browser window to stop.")
    rec.wait_closed()
    rec.stop()
    print(f"Saved {len(rec.events)} events.")
    return 0


def cmd_steps(a: argparse.Namespace) -> int:
    steps = normalize(read_events(a.recording))
    if a.json:
        print(json.dumps([s.to_dict() for s in steps], ensure_ascii=False, indent=1))
    else:
        for i, s in enumerate(steps, 1):
            print(f"{i:3}. {s.describe()}")
    return 0


def cmd_generalize(a: argparse.Namespace) -> int:
    from hermes_teach.generalize import heuristic_procedure, llm_generalize
    steps = normalize(read_events(a.recording))
    proc = heuristic_procedure(steps, a.name, a.description or "", source_recording=str(a.recording))
    if a.platform:
        proc.platforms = [a.platform]
    if a.llm:
        from hermes_teach.llm import from_env
        variations = a.variations or ""
        if variations.startswith("@"):
            variations = Path(variations[1:]).read_text(encoding="utf-8")
        proc = llm_generalize(from_env(), steps, proc, variations)
    out = Path(a.out or f"{proc.name}.yaml")
    proc.save(out)
    print(f"Wrote {out} ({len(proc.steps)} steps, params: {', '.join(proc.params) or 'none'}).")
    unresolved = [c.name for c in proc.credentials.values() if c.item.startswith("FILL-ME")]
    if unresolved:
        print(f"Set the Bitwarden item name for: {', '.join(unresolved)} in {out}")
    return 0


def _build_runner(proc: Procedure, a: argparse.Namespace, metrics: Metrics | None) -> Any:
    from hermes_teach.drivers.base import DryRunDriver
    from hermes_teach.runner import Runner
    from hermes_teach.secrets import SecretStore

    needs_desktop = any(not s.action.startswith("browser.") for s in proc.steps)
    if a.dry_run:
        desktop: Any = DryRunDriver()
        browser_factory: Any = lambda: desktop  # noqa: E731
    else:
        desktop = None
        if needs_desktop:
            from hermes_teach.drivers.desktop import DesktopDriver
            desktop = DesktopDriver()

        def browser_factory() -> Any:
            from hermes_teach.drivers.browser import BrowserDriver
            return BrowserDriver(headless=a.headless, user_data_dir=a.profile,
                                 executable_path=os.environ.get("HERMES_TEACH_CHROMIUM"))
    recover = None
    if a.recover and desktop is not None and not a.dry_run:
        from hermes_teach.llm import from_env
        from hermes_teach.recovery import VisionRecovery
        recover = VisionRecovery(from_env(), desktop)
    return Runner(proc, desktop=desktop, browser_factory=browser_factory,
                  secrets=SecretStore(proc.credentials, override=a.secrets_provider),
                  confirm=(lambda q: True) if a.yes else _ask, metrics=metrics,
                  log=lambda m: print("  " + m), resolve_secrets=not a.dry_run, recover=recover)


def cmd_run(a: argparse.Namespace) -> int:
    proc = Procedure.load(a.procedure)
    metrics = None if a.dry_run else _metrics()
    runner = _build_runner(proc, a, metrics)
    params = _params(a.param)
    if a.dry_run:
        values = proc.resolve_params(params)
        for i, s, will in runner.plan(params):
            print(f"{'RUN ' if will else 'skip'} {i:3}. {s.action} {s.target.describe()} {render(s.text, values)}")
        return 0
    print(f"Running {proc.name} v{proc.version}")
    res = runner.run(params)
    print(f"Result: {res.status}" + (f" at step {res.failed_step}: {res.error}" if res.error else ""))
    if runner.recovered:
        print(f"LLM recovered steps: {runner.recovered} (procedure needs fixing before promotion)")
    if metrics is not None and res.run_id and res.status == "ok" and not a.no_verdict:
        verdict = "accepted" if _ask("Was the result correct?") else "rejected"
        metrics.set_verdict(res.run_id, verdict)
        st = metrics.stats(proc.name, proc.version, a.streak)
        print(f"Verdict: {verdict}. Streak {st.current_streak}/{a.streak}.")
        if st.candidate:
            print(f"'{proc.name}' is a promotion candidate: `hermes-teach compile {a.procedure}`")
    return 0 if res.status == "ok" else 1


def cmd_verdict(a: argparse.Namespace) -> int:
    m = _metrics()
    run_id = a.run
    if run_id is None and a.name:
        run_id = m.last_run_id(a.name)
    if run_id is None:
        row = m.db.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        run_id = row[0] if row else None
    if run_id is None:
        print("no runs recorded")
        return 1
    m.set_verdict(int(run_id), "accepted" if a.verdict == "accept" else "rejected")
    print(f"run {run_id}: {a.verdict}ed")
    return 0


def cmd_metrics(a: argparse.Namespace) -> int:
    m = _metrics()
    rows = [(n, v) for n, v in m.all_procedures() if not a.name or n == a.name]
    if not rows:
        print("no runs recorded")
    for n, v in rows:
        st = m.stats(n, v, a.streak)
        flag = "  <- promotion candidate" if st.candidate else ""
        print(f"{n} v{v}: runs={st.runs} ok={st.ok} accepted={st.accepted} failed={st.failed} "
              f"streak={st.current_streak}/{a.streak} avg={st.avg_duration:.1f}s "
              f"promoted={','.join(st.promoted) or '-'}{flag}")
        hot = m.failure_hotspots(n, v)
        if hot:
            print("   failures by step: " + ", ".join(f"#{s}x{c}" for s, c in hot))
    return 0


def cmd_compile(a: argparse.Namespace) -> int:
    from hermes_teach.compile import auto_target, compile_procedure
    proc = Procedure.load(a.procedure)
    m = _metrics()
    st = m.stats(proc.name, proc.version, a.streak)
    if st.current_streak < a.streak and not a.force:
        print(f"'{proc.name}' has {st.current_streak}/{a.streak} accepted runs in a row; "
              "use --force to compile anyway.")
        return 1
    target = a.target or auto_target(proc, _os_name())
    code = compile_procedure(proc, target)
    ext = ".au3" if target == "autoit" else ".py"
    out = Path(a.out or f"{proc.name}.{target}{ext}")
    out.write_text(code, encoding="utf-8")
    m.mark_promoted(proc.name, proc.version, target, str(out))
    print(f"Wrote {out}")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from hermes_teach.skill_export import export_skill
    d = export_skill(Procedure.load(a.procedure), a.dir)
    print(f"Skill exported to {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hermes-teach", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="record desktop input (Windows / Linux X11)")
    p.add_argument("--out", default="recording.jsonl")
    p.add_argument("--screenshots", help="save a crop around every click here")
    p.add_argument("--delay", type=float, default=0)
    p.add_argument("--max-seconds", type=float, default=0)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("record-browser", help="record a browser session with selectors")
    p.add_argument("url")
    p.add_argument("--out", default="recording.jsonl")
    p.add_argument("--profile", help="persistent browser profile dir")
    p.set_defaults(fn=cmd_record_browser)

    p = sub.add_parser("steps", help="show normalized steps of a recording")
    p.add_argument("recording")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_steps)

    p = sub.add_parser("generalize", help="recording -> parameterized procedure")
    p.add_argument("recording")
    p.add_argument("--name", required=True)
    p.add_argument("--description")
    p.add_argument("--variations", help="how the procedure varies (text or @file)")
    p.add_argument("--llm", action="store_true", help="let the LLM refine params and conditions")
    p.add_argument("--platform", choices=["windows", "linux"])
    p.add_argument("--out")
    p.set_defaults(fn=cmd_generalize)

    p = sub.add_parser("run", help="execute a procedure")
    p.add_argument("procedure")
    p.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", action="store_true", help="auto-confirm confirm-steps")
    p.add_argument("--no-verdict", action="store_true", help="don't ask whether the result was right")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--profile", help="persistent browser profile dir")
    p.add_argument("--secrets-provider", choices=["bitwarden", "bws", "env"])
    p.add_argument("--recover", action="store_true", help="LLM vision fallback for lost click targets")
    p.add_argument("--streak", type=int, default=DEFAULT_STREAK)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("verdict", help="accept or reject the last run")
    p.add_argument("verdict", choices=["accept", "reject"])
    p.add_argument("--name")
    p.add_argument("--run", type=int)
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("metrics", help="success / acceptance statistics")
    p.add_argument("name", nargs="?")
    p.add_argument("--streak", type=int, default=DEFAULT_STREAK)
    p.set_defaults(fn=cmd_metrics)

    p = sub.add_parser("compile", help="turn a proven procedure into a script")
    p.add_argument("procedure")
    p.add_argument("--target", choices=["playwright", "autoit", "xdotool"])
    p.add_argument("--out")
    p.add_argument("--force", action="store_true")
    p.add_argument("--streak", type=int, default=DEFAULT_STREAK)
    p.set_defaults(fn=cmd_compile)

    p = sub.add_parser("export-skill", help="write a Hermes skill directory")
    p.add_argument("procedure")
    p.add_argument("--dir", default=str(Path.home() / ".hermes" / "skills"))
    p.set_defaults(fn=cmd_export)

    a = ap.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
