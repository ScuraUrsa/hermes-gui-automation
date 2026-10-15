"""Change procedures and write workflows from plain-language instructions (LLM).

* ``llm_edit`` — "if the country is DE click 'Lieferung' instead of 'Dostawa'",
  "add a parameter for the due date and type it into the Due field": the LLM
  rewrites the procedure YAML, the result is validated and the version is
  bumped (which resets the acceptance streak, as a changed procedure must prove
  itself again).
* ``draft_workflow`` — "every time an invoice e-mail arrives pay the amount
  from the mail, above 500 PLN ask me first, then log it in Excel": the LLM
  writes a workflow YAML out of the available procedures and tiles; validated,
  with one retry on errors.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

import yaml

from hermes_teach.generalize import SYSTEM as PROCEDURE_FORMAT
from hermes_teach.generalize import extract_yaml
from hermes_teach.llm import LLM
from hermes_teach.procedure import Procedure, ProcedureError
from hermes_teach.tiles import TILE_DOCS
from hermes_teach.workflow import Workflow

EDIT_SYSTEM = PROCEDURE_FORMAT + """
You are now EDITING an existing procedure according to the user's instruction. Rules for edits:
- Change only what the instruction requires; keep every other step and every target field as is.
- "Instead of X do Y when <condition>": add a param for the condition (bool or enum with a sensible default
  equal to the recorded behaviour), put `when` on the original step and add the alternative step with the
  opposite `when`. If the alternative's target was never recorded, infer it from the names in the window /
  page and mark it with note: "inferred, verify".
- "Also do / additionally click / type ...": insert the new step at the right place, with a param if the value varies.
- "Skip / remove ...": delete the step (or guard it with `when` if the instruction is conditional).
- New values that change between runs become params; never hardcode passwords.
- Keep `name`; do not touch `version` (it is bumped automatically).
"""

WORKFLOW_FORMAT = """You write workflows for hermes-teach, an automation agent that replays procedures the
user recorded on their own computer. Output ONLY one YAML document in a ```yaml block.

Workflow format:
name: kebab-case
description: one sentence
version: 1
on:                                  # triggers (list); manual: {} lets the user start it by hand
  - email: {from: "<glob or re:regex>", subject: "<glob or re:regex>", host: imap.example.com, user: "...",
            credential: <credential name>}
            # payload: trigger.from, trigger.subject, trigger.body, trigger.attachments
  - file: {dir: "~/Downloads", glob: "*.pdf"}   # payload: trigger.path, trigger.name
  - schedule: {every: 1d}                       # 30s 15m 2h 1d
  - manual: {}
inputs:   {<name>: {type: string|number|int|bool|enum, description, default?, required?, choices?}}
credentials: {<name>: {provider: bitwarden, item: "<Bitwarden item>", fields: [username, password]}}  # e-mail login
extract:  {<name>: {from: trigger.body, regex: "<regex with one group>", type: number|int|string|bool, default?,
                    llm: "<question for the model when there is no regex / no match>", required?}}
steps:
  - id: <unique id>
    uses: <tile>
    if: "<expression>"                 # optional; e.g. "extract.amount <= inputs.threshold"
    needs: [<earlier step ids>]        # runs only if those succeeded
    confirm: true                      # always ask the user before this step
    confirm_when: "<expression>"       # ask only when true (thresholds, unusual cases)
    confirm_text: "text with {{ templates }} shown to the user"
    continue_on_error: false
    always: true                       # run even after an earlier failure (e.g. a "not paid" notify)
    <tile fields...>
outputs: {<name>: "{{ expression }}"}

Tiles (fields -> outputs available as steps.<id>.<output>):
""" + "\n".join(f"  {k}: {v}" for k, v in TILE_DOCS.items()) + """

Expressions: Python-like, over inputs.*, trigger.*, extract.*, steps.<id>.*, env.*, now, today
(== != < > <= >= in not and or + - * /; dotted lookups; no calls). Input and extract names may be used bare.
Templates: {{ expression }}. A value that is exactly one template keeps its type (numbers stay numbers).
Money: use type: number for amounts; Polish amounts like "1 234,56 zł" are parsed.

Rules:
- Only use procedures from the list given (with their exact param names); never invent procedures.
  If something needed has no procedure, add an `ask` or `notify` step that tells the user what is missing.
- Anything that sends money, e-mails, deletes or submits gets confirm: true, or confirm_when with the user's
  threshold as an input with a default.
- When the user says "ask me", use confirm_when / an ask tile whose question contains the relevant values.
- Keep it short: no steps the user did not ask for, except a final notify summarizing what happened.
"""


def _procedure_summary(procs: list[Procedure]) -> str:
    if not procs:
        return "(no procedures available)"
    out = []
    for p in procs:
        params = ", ".join(f"{n}: {q.type}" + (f"={q.default!r}" if q.default is not None else "")
                           for n, q in p.params.items()) or "none"
        out.append(f"- {p.name}: {p.description or '(no description)'}; params: {params}"
                   + ("; requires confirmation" if p.requires_confirmation else ""))
    return "\n".join(out)


def _workflow_summary(wfs: list[Workflow]) -> str:
    if not wfs:
        return ""
    return "\nExisting workflows that can be used with uses: workflow:\n" + "\n".join(
        f"- {w.name}: {w.description}; inputs: {', '.join(w.inputs) or 'none'}" for w in wfs)


def llm_edit(llm: LLM, proc: Procedure, instruction: str, attempts: int = 2) -> Procedure:
    prompt = ("Current procedure:\n```yaml\n" + proc.to_yaml() + "```\n\nUser's instruction:\n"
              + instruction.strip() + "\n\nReturn the full edited procedure YAML.")
    last_err = ""
    for _ in range(attempts):
        reply = llm.complete(EDIT_SYSTEM, prompt if not last_err else
                             prompt + f"\n\nYour previous answer was invalid: {last_err}\nFix it.")
        try:
            data = extract_yaml(reply)
            data["name"] = proc.name
            data["version"] = proc.version + 1
            new = Procedure.from_dict(data)
            new.source_recording = proc.source_recording
            return new
        except (ProcedureError, yaml.YAMLError, TypeError, ValueError, KeyError) as e:
            last_err = str(e)
    raise ProcedureError(f"LLM could not produce a valid procedure: {last_err}")


def draft_workflow(llm: LLM, description: str, procedures: list[Procedure],
                   workflows: list[Workflow] | None = None, name: str = "", attempts: int = 2) -> Workflow:
    prompt = ("Available procedures:\n" + _procedure_summary(procedures) + _workflow_summary(workflows or [])
              + "\n\nWhat the user wants:\n" + description.strip()
              + (f"\n\nName the workflow '{name}'." if name else "") + "\n\nReturn the workflow YAML.")
    last_err = ""
    known = {p.name for p in procedures}
    for _ in range(attempts):
        reply = llm.complete(WORKFLOW_FORMAT, prompt if not last_err else
                             prompt + f"\n\nYour previous answer was invalid: {last_err}\nFix it.")
        try:
            data = extract_yaml(reply)
            if name:
                data["name"] = name
            wf = Workflow.from_dict(data)
            missing = [s.config.get("procedure") for s in wf.steps
                       if s.uses == "procedure" and str(s.config.get("procedure")) not in known]
            if missing and known:
                raise ProcedureError(f"unknown procedures {missing}; available: {sorted(known)}")
            _check_procedure_params(wf, procedures)
            return wf
        except (ProcedureError, yaml.YAMLError, TypeError, ValueError, KeyError) as e:
            last_err = str(e)
    raise ProcedureError(f"LLM could not produce a valid workflow: {last_err}")


def _check_procedure_params(wf: Workflow, procedures: list[Procedure]) -> None:
    by_name = {p.name: p for p in procedures}
    for s in wf.steps:
        if s.uses != "procedure":
            continue
        proc = by_name.get(str(s.config.get("procedure")))
        if proc is None:
            continue
        given = set((s.config.get("with") or {}).keys())
        unknown = given - set(proc.params)
        if unknown:
            raise ProcedureError(f"step {s.id}: procedure {proc.name} has no params {sorted(unknown)}; "
                                 f"it has {sorted(proc.params)}")
        missing = [p.name for p in proc.params.values() if p.required and p.default is None and p.name not in given]
        if missing:
            raise ProcedureError(f"step {s.id}: procedure {proc.name} needs params {missing}")


def diff(before: str, after: str, name: str = "procedure") -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"{name} (before)", f"{name} (after)"))


def explain_change(proc_before: Procedure, proc_after: Procedure) -> str:
    """One-line human summary of what an edit did (params and step counts)."""
    added = sorted(set(proc_after.params) - set(proc_before.params))
    removed = sorted(set(proc_before.params) - set(proc_after.params))
    parts = [f"steps {len(proc_before.steps)} -> {len(proc_after.steps)}"]
    if added:
        parts.append("new params: " + ", ".join(added))
    if removed:
        parts.append("removed params: " + ", ".join(removed))
    inferred = sum(1 for s in proc_after.steps if "inferred" in s.note.lower())
    if inferred:
        parts.append(f"{inferred} inferred step(s) to verify")
    return "; ".join(parts)


def _json_default(o: Any) -> Any:
    return str(o)


def describe_workflow(wf: Workflow) -> str:
    lines = [f"{wf.name} v{wf.version}: {wf.description}".strip()]
    if wf.on:
        lines.append("triggers: " + ", ".join(
            t.kind + ("" if not t.config else " " + json.dumps(
                {k: v for k, v in t.config.items() if k in ("from", "subject", "glob", "dir", "every")},
                ensure_ascii=False, default=_json_default)) for t in wf.on))
    if wf.inputs:
        lines.append("inputs: " + ", ".join(f"{p.name}={p.default!r}" if p.default is not None else p.name
                                            for p in wf.inputs.values()))
    if wf.extract:
        lines.append("extract: " + ", ".join(f"{e.name} <- {e.source}" for e in wf.extract))
    for i, s in enumerate(wf.steps, 1):
        flags = []
        if s.if_:
            flags.append(f"if {s.if_}")
        if s.needs:
            flags.append(f"needs {','.join(s.needs)}")
        if s.confirm:
            flags.append("asks first")
        if s.confirm_when:
            flags.append(f"asks when {s.confirm_when}")
        lines.append(f"{i:3}. {s.describe()}" + (f"   [{'; '.join(flags)}]" if flags else ""))
    return "\n".join(lines)

