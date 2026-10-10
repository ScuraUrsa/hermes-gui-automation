"""Export a procedure as a Hermes skill directory (SKILL.md + procedure.yaml)."""

from __future__ import annotations

from pathlib import Path

from hermes_teach.procedure import Procedure


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
