"""hermes-teach command line.

    hermes-teach record --out rec.jsonl            # desktop, Ctrl+Shift+F12 stops
    hermes-teach record-browser https://... --out rec.jsonl
    hermes-teach steps rec.jsonl
    hermes-teach generalize rec.jsonl --name invoice --variations "..." [--llm] --out proc.yaml
    hermes-teach run proc.yaml --param supplier=ACME [--dry-run] [--yes]
    hermes-teach verdict accept|reject
    hermes-teach metrics [name]
    hermes-teach compile proc.yaml [--target playwright|autoit|xdotool]
    hermes-teach export-skill proc.yaml|wf.yaml --dir ~/.hermes/skills
    hermes-teach edit proc.yaml "when country is DE click Lieferung instead of Dostawa"
    hermes-teach workflow draft "every invoice mail: pay, ask me above 500 PLN, log to Excel" --out wf.yaml
    hermes-teach workflow validate|show wf.yaml
    hermes-teach workflow run wf.yaml [--input k=v] [--payload event.json] [--dry-run] [--channel matrix]
    hermes-teach workflow watch [--once] [--interval 60]      # e-mail / file / schedule triggers
    hermes-teach workflow tiles
    hermes-teach ask "Pay 1200 PLN?" [--options tak,nie]       # test the question channel
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


def _build_runner(proc: Procedure, a: argparse.Namespace, metrics: Metrics | None,
                  confirm: Any = None) -> Any:
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
                  confirm=confirm or ((lambda q: True) if a.yes else _ask), metrics=metrics,
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
    import yaml

    from hermes_teach.skill_export import export_skill, export_workflow_skill
    data = yaml.safe_load(Path(a.procedure).read_text(encoding="utf-8")) or {}
    if _is_workflow(data):
        from hermes_teach.workflow import Workflow
        d = export_workflow_skill(Workflow.from_dict(data), a.dir)
    else:
        d = export_skill(Procedure.from_dict(data), a.dir)
    print(f"Skill exported to {d}")
    return 0


def _is_workflow(data: dict[str, Any]) -> bool:
    steps = data.get("steps") or []
    has_uses = any(isinstance(st, dict) and "uses" in st for st in steps)
    return bool(data.get("on")) or bool(data.get("inputs")) or has_uses


# --- natural-language edits and workflows -------------------------------------
def cmd_edit(a: argparse.Namespace) -> int:
    from hermes_teach.llm import from_env
    from hermes_teach.refine import diff, explain_change, llm_edit
    proc = Procedure.load(a.procedure)
    instruction = a.instruction
    if instruction.startswith("@"):
        instruction = Path(instruction[1:]).read_text(encoding="utf-8")
    new = llm_edit(from_env(), proc, instruction)
    print(diff(proc.to_yaml(), new.to_yaml(), proc.name))
    print(explain_change(proc, new))
    out = Path(a.out or a.procedure)
    if a.show:
        print(f"(not saved; drop --show to write {out})")
        return 0
    new.save(out)
    print(f"Wrote {out} as v{new.version} (acceptance streak starts again for the new version).")
    return 0


def _channel(a: argparse.Namespace) -> Any:
    from hermes_teach import channels
    return channels.from_env(getattr(a, "channel", None), yes=bool(getattr(a, "yes", False)))


def _library(a: argparse.Namespace) -> Any:
    from hermes_teach.workflow import Library
    dirs = [Path(d) for d in (getattr(a, "dir", None) or [])] or None
    return Library(dirs=([*dirs, home()] if dirs else None), skills_dir=getattr(a, "skills_dir", None))


def _load_workflow(a: argparse.Namespace, ref: str) -> Any:
    return _library(a).workflow(ref)


def _wf_runner(a: argparse.Namespace, wf: Any, channel: Any, metrics: Metrics | None) -> Any:
    from hermes_teach.channels import is_yes
    from hermes_teach.workflow import WorkflowRunner
    lib = _library(a)

    def runner_factory(proc: Procedure) -> Any:
        def confirm(q: str) -> bool:
            return True if a.yes or a.dry_run else is_yes(channel.ask(q, None))
        return _build_runner(proc, a, None if a.dry_run else _metrics(), confirm=confirm)

    return WorkflowRunner(wf, library=lib, channel=channel, runner_factory=runner_factory, metrics=metrics,
                          dry_run=a.dry_run, log=lambda m: print("  " + m), runs_dir=home() / "runs")


def _payload(a: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(a, "payload", None):
        return None
    if a.payload == "-":
        return json.load(sys.stdin)
    return json.loads(Path(a.payload).read_text(encoding="utf-8"))


def cmd_wf_validate(a: argparse.Namespace) -> int:
    from hermes_teach.refine import describe_workflow
    wf = _load_workflow(a, a.workflow)
    print(describe_workflow(wf) if a.cmd_wf == "show" else f"{wf.name} v{wf.version}: valid ({len(wf.steps)} steps)")
    lib = _library(a)
    missing = []
    for st in wf.steps:
        try:
            if st.uses == "procedure":
                lib.procedure(str(st.config["procedure"]))
            elif st.uses == "workflow":
                lib.workflow(str(st.config["workflow"]))
        except Exception as e:  # noqa: BLE001
            missing.append(str(e))
    for m in missing:
        print(f"warning: {m}")
    return 1 if missing and a.cmd_wf == "validate" else 0


def cmd_wf_run(a: argparse.Namespace) -> int:
    wf = _load_workflow(a, a.workflow)
    channel = _channel(a)
    metrics = None if a.dry_run else _metrics()
    runner = _wf_runner(a, wf, channel, metrics)
    inputs = _params(a.input)
    res = runner.run(inputs, _payload(a), mode="manual" if a.cmd_wf == "run" else "trigger")
    if res.outputs:
        print("outputs: " + json.dumps(res.outputs, ensure_ascii=False, default=str))
    if res.run_dir:
        print(f"run record: {res.run_dir}")
    return 0 if res.status == "ok" else 1


def cmd_wf_watch(a: argparse.Namespace) -> int:
    from hermes_teach.watch import watch
    channel = _channel(a)
    lib = _library(a)
    metrics = _metrics()

    def run(wf: Any, payload: dict[str, Any]) -> Any:
        res = _wf_runner(a, wf, channel, metrics).run({}, payload, mode="trigger")
        print(f"{wf.name}: {res.status}" + (f" ({res.error})" if res.error else ""))
        return res

    print(f"watching {len(lib.workflows())} workflow file(s) in {', '.join(str(d) for d in lib.dirs)}"
          + ("" if a.once else f" every {a.interval}s"))
    try:
        watch(lib, run, home() / "state", interval=a.interval, once=a.once, secrets_override=a.secrets_provider)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_wf_draft(a: argparse.Namespace) -> int:
    from hermes_teach.llm import from_env
    from hermes_teach.refine import describe_workflow, draft_workflow
    lib = _library(a)
    procs = []
    for ref in a.procedure or []:
        procs.append(lib.procedure(ref))
    if not procs:
        for d in lib.dirs:
            for p in list(d.glob("*.yaml")) + list((d / "procedures").glob("*.yaml")):
                try:
                    procs.append(Procedure.load(p))
                except Exception:  # noqa: BLE001 - not every yaml is a procedure
                    continue
    desc = a.description
    if desc.startswith("@"):
        desc = Path(desc[1:]).read_text(encoding="utf-8")
    wf = draft_workflow(from_env(), desc, procs, name=a.name or "")
    out = Path(a.out or f"{wf.name}.yaml")
    wf.save(out)
    print(describe_workflow(wf))
    print(f"Wrote {out}. Check it with `hermes-teach workflow run {out} --dry-run`.")
    return 0


def cmd_wf_tiles(a: argparse.Namespace) -> int:
    from hermes_teach.tiles import TILE_DOCS
    for k, v in TILE_DOCS.items():
        print(f"{k:14} {v}")
    return 0


def cmd_wf_list(a: argparse.Namespace) -> int:
    from hermes_teach.workflow import Workflow
    lib = _library(a)
    for p in lib.workflows():
        try:
            wf = Workflow.load(p)
            print(f"{wf.name:30} {', '.join(t.kind for t in wf.on) or 'manual':20} {p}")
        except Exception as e:  # noqa: BLE001
            print(f"{p}: invalid ({e})")
    return 0


def cmd_ask(a: argparse.Namespace) -> int:
    channel = _channel(a)
    options = [o.strip() for o in a.options.split(",")] if a.options else None
    answer = channel.ask(a.question, options, timeout=a.timeout)
    print(json.dumps({"answer": answer}, ensure_ascii=False))
    return 0 if answer is not None else 1


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

    p = sub.add_parser("export-skill", help="write a Hermes skill directory (procedure or workflow)")
    p.add_argument("procedure", metavar="procedure-or-workflow.yaml")
    p.add_argument("--dir", default=str(Path.home() / ".hermes" / "skills"))
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("edit", help="change a procedure with a plain-language instruction (LLM)")
    p.add_argument("procedure")
    p.add_argument("instruction", help="text or @file")
    p.add_argument("--out", help="write here instead of overwriting")
    p.add_argument("--show", action="store_true", help="only print the diff")
    p.set_defaults(fn=cmd_edit)

    p = sub.add_parser("ask", help="send a question through the configured channel (test it)")
    p.add_argument("question")
    p.add_argument("--options", help="comma separated")
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--channel", choices=["console", "command", "matrix", "file"])
    p.set_defaults(fn=cmd_ask)

    w = sub.add_parser("workflow", help="chain procedures and tiles; triggers, thresholds, questions")
    wsub = w.add_subparsers(dest="cmd_wf", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", action="append", help="extra directory with procedures/ and workflows/")
    common.add_argument("--skills-dir", help="Hermes skills directory (default ~/.hermes/skills)")
    runopts = argparse.ArgumentParser(add_help=False)
    runopts.add_argument("--dry-run", action="store_true")
    runopts.add_argument("--yes", action="store_true", help="auto-confirm every question")
    runopts.add_argument("--channel", choices=["console", "command", "matrix", "file"])
    runopts.add_argument("--headless", action="store_true")
    runopts.add_argument("--profile", help="persistent browser profile dir")
    runopts.add_argument("--secrets-provider", choices=["bitwarden", "bws", "env"])
    runopts.add_argument("--recover", action="store_true")
    runopts.add_argument("--no-verdict", action="store_true", default=True, help=argparse.SUPPRESS)
    runopts.add_argument("--streak", type=int, default=DEFAULT_STREAK, help=argparse.SUPPRESS)

    for name in ("validate", "show"):
        p = wsub.add_parser(name, parents=[common], help="check a workflow" if name == "validate" else "print its plan")
        p.add_argument("workflow")
        p.set_defaults(fn=cmd_wf_validate)
    for name in ("run", "trigger"):
        p = wsub.add_parser(name, parents=[common, runopts],
                            help="run by hand" if name == "run" else "run with an event payload (JSON file or -)")
        p.add_argument("workflow")
        p.add_argument("--input", action="append", default=[], metavar="NAME=VALUE")
        p.add_argument("--payload", help="JSON file with the trigger payload ('-' = stdin)")
        p.set_defaults(fn=cmd_wf_run)
    p = wsub.add_parser("watch", parents=[common, runopts], help="poll e-mail/file/schedule triggers")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=float, default=60)
    p.set_defaults(fn=cmd_wf_watch)
    p = wsub.add_parser("draft", parents=[common], help="write a workflow from a description (LLM)")
    p.add_argument("description", help="text or @file")
    p.add_argument("--procedure", action="append", help="procedures it may use (default: all found)")
    p.add_argument("--name")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_wf_draft)
    p = wsub.add_parser("tiles", help="list built-in tiles")
    p.set_defaults(fn=cmd_wf_tiles)
    p = wsub.add_parser("list", parents=[common], help="workflows in the library")
    p.set_defaults(fn=cmd_wf_list)

    a = ap.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    sys.exit(main())
