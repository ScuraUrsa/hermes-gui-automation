"""Export a procedure or workflow as a Hermes skill directory (SKILL.md + procedure.yaml / workflow.yaml)."""

from __future__ import annotations

from pathlib import Path

from hermes_teach.procedure import Procedure
from hermes_teach.workflow import Workflow


def skill_markdown(proc: Procedure) -> str:
    platforms = ", ".join(proc.platforms)
    lines = [
        "---",
        f"name: {proc.name}",
        f"description: {proc.description or proc.name} (recorded procedure; replays the user's own steps"
        " with parameters)",
        f"version: {proc.version}.0.0",
        f"platforms: [{platforms}]",
        "tags: [recorded-procedure, hermes-teach, gui]",
        "---",
        "",
        f"# {proc.name}",
        "",
        proc.description or "",
        "",
        "This skill was recorded from the user's own screen actions with hermes-teach and",
        "generalized into the parameters below. Run it, do not improvise the steps.",
        "",
        "## Parameters",
        "",
    ]
    if proc.params:
        lines += ["| name | type | default | meaning |", "|---|---|---|---|"]
        for p in proc.params.values():
            extra = f" (one of: {', '.join(map(str, p.choices))})" if p.choices else ""
            default = "" if p.default is None else f"`{p.default}`"
            lines.append(f"| `{p.name}` | {p.type} | {default} | {p.description}{extra} |")
    else:
        lines.append("None.")
    lines += ["", "## Credentials", ""]
    if proc.credentials:
        for c in proc.credentials.values():
            lines.append(f"- `{c.name}`: {c.provider} item **{c.item}** (fields: {', '.join(c.fields)})")
        lines += ["", "Before running, make sure the user has unlocked Bitwarden (`bw unlock`) and",
                  "`BW_SESSION` is exported in the environment of the run. Never ask the user to paste",
                  "a password into the chat; never print secrets."]
    else:
        lines.append("None.")
    lines += [
        "",
        "## How to run",
        "",
        "1. Collect parameter values from the user's request; ask only for values that are",
        "   missing and have no default.",
        "2. Preview: `hermes-teach run procedure.yaml --dry-run --param name=value ...`",
        "3. Run: `hermes-teach run procedure.yaml --param name=value ...`"
        + (" (the user must confirm; this procedure has irreversible steps)" if proc.requires_confirmation else ""),
        "4. Show the user the result and ask whether it is correct, then record the verdict:",
        "   `hermes-teach verdict accept` or `hermes-teach verdict reject --note \"why\"`.",
        "5. `hermes-teach metrics " + proc.name + "` shows the acceptance streak; when it reports",
        "   *promotion candidate*, offer the user `hermes-teach compile procedure.yaml` to turn it",
        "   into a Playwright / AutoIt / xdotool script.",
        "",
        "## Steps",
        "",
    ]
    for i, s in enumerate(proc.steps, 1):
        cond = f" — only if `{s.when}`" if s.when else ""
        conf = " — asks for confirmation" if s.confirm else ""
        txt = f" `{s.text}`" if s.text and not s.sensitive else (" (secret)" if s.sensitive else "")
        lines.append(f"{i}. {s.action} {s.target.describe()}{txt}{cond}{conf}")
    return "\n".join(lines) + "\n"


def export_skill(proc: Procedure, out_dir: str | Path) -> Path:
    d = Path(out_dir) / proc.name
    d.mkdir(parents=True, exist_ok=True)
    proc.save(d / "procedure.yaml")
    (d / "SKILL.md").write_text(skill_markdown(proc), encoding="utf-8")
    return d


def workflow_markdown(wf: Workflow) -> str:
    triggers = ", ".join(t.kind for t in wf.on) or "manual"
    lines = [
        "---",
        f"name: {wf.name}",
        f"description: {wf.description or wf.name} (workflow of recorded procedures and tiles; triggers: {triggers})",
        f"version: {wf.version}.0.0",
        "tags: [workflow, hermes-teach, automation]",
        "---",
        "",
        f"# {wf.name}",
        "",
        wf.description or "",
        "",
        "This workflow chains procedures the user recorded with hermes-teach and built-in tiles.",
        "Run it with hermes-teach; do not improvise the steps.",
        "",
        "## Triggers",
        "",
    ]
    if wf.on:
        for t in wf.on:
            cfg = {k: v for k, v in t.config.items() if k not in ("credential", "host", "user", "port", "ssl")}
            lines.append(f"- `{t.kind}` {cfg if cfg else ''}".rstrip())
        if any(t.kind in ("email", "file", "schedule") for t in wf.on):
            lines += ["", "Automatic triggers fire from `hermes-teach workflow watch` (cron/systemd: `--once`).",
                      "An external event (Hermes webhook, Home Assistant) can start it with",
                      f"`hermes-teach workflow trigger {wf.name} --payload event.json`."]
    else:
        lines.append("Manual only.")
    lines += ["", "## Inputs", ""]
    if wf.inputs:
        lines += ["| name | type | default | meaning |", "|---|---|---|---|"]
        for p in wf.inputs.values():
            default = "" if p.default is None else f"`{p.default}`"
            lines.append(f"| `{p.name}` | {p.type} | {default} | {p.description} |")
    else:
        lines.append("None.")
    if wf.extract:
        lines += ["", "## Values taken from the event", ""]
        for e in wf.extract:
            how = f"regex `{e.regex}`" if e.regex else (f"LLM: {e.llm}" if e.llm else "as is")
            lines.append(f"- `{e.name}` ({e.type}) from `{e.source}`, {how}")
    lines += [
        "",
        "## How to run",
        "",
        "1. Collect input values from the user's request; ask only for missing values without defaults.",
        f"2. Preview: `hermes-teach workflow run {wf.name} --dry-run --input name=value ...`",
        f"3. Run: `hermes-teach workflow run {wf.name} --input name=value ...`",
        "   Steps marked below as asking stop and wait for the user's answer on the configured channel",
        "   (console, Matrix, Hermes). Never pass `--yes` unless the user asked for unattended runs.",
        "4. Report the run summary and the record under `~/.hermes/teach/runs/`.",
        "",
        "## Steps",
        "",
    ]
    for i, s in enumerate(wf.steps, 1):
        flags = []
        if s.if_:
            flags.append(f"only if `{s.if_}`")
        if s.needs:
            flags.append(f"after {', '.join(s.needs)}")
        if s.confirm:
            flags.append("asks the user first")
        if s.confirm_when:
            flags.append(f"asks the user when `{s.confirm_when}`")
        lines.append(f"{i}. {s.describe()}" + (" — " + "; ".join(flags) if flags else ""))
    return "\n".join(lines) + "\n"


def export_workflow_skill(wf: Workflow, out_dir: str | Path) -> Path:
    d = Path(out_dir) / wf.name
    d.mkdir(parents=True, exist_ok=True)
    wf.save(d / "workflow.yaml")
    (d / "SKILL.md").write_text(workflow_markdown(wf), encoding="utf-8")
    return d
