"""Workflows: chain recorded procedures and built-in tiles, GitHub-Actions style.

A workflow is a YAML document::

    name: pay-invoice-from-email
    on:
      - email: {from: "*@invoices.example.com", subject: "re:(?i)invoice|faktura"}
      - manual: {}
    inputs:
      threshold: {type: number, default: 500, description: ask above this amount}
    credentials:
      mail: {provider: bitwarden, item: "Gmail IMAP"}
    extract:
      amount:  {from: trigger.body, regex: "(\\\\d[\\\\d ]*[,.]\\\\d{2})\\\\s*(?:zł|PLN)", type: number}
      account: {from: trigger.body, regex: "\\\\b(\\\\d{2}(?: ?\\\\d{4}){6})\\\\b"}
    steps:
      - id: pay
        uses: procedure
        procedure: bank-transfer
        with: {amount: "{{ extract.amount }}", account: "{{ extract.account }}"}
        confirm_when: "extract.amount > inputs.threshold"
        confirm_text: "Invoice for {{ extract.amount }} PLN is above {{ inputs.threshold }}. Pay?"
      - id: log
        uses: table.append
        needs: [pay]
        file: ~/payments.xlsx
        row: {date: "{{ today }}", amount: "{{ extract.amount }}", status: "{{ steps.pay.status }}"}
      - id: report
        uses: workflow
        workflow: refresh-excel-report
        needs: [log]
    outputs:
      paid: "{{ steps.pay.ok }}"

Context available to ``if``, ``confirm_when`` and ``{{ }}`` templates:
``inputs.*``, ``trigger.*`` (the event payload), ``extract.*``, ``steps.<id>.*``
(``status``, ``ok``, ``skipped`` and the step's outputs), ``env.*``, ``now``,
``today``. Input and extract names can also be used bare. A template that is
exactly one ``{{ expr }}`` keeps the value's type (numbers stay numbers).
Expressions use the extended safe grammar from ``hermes_teach.procedure``.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from hermes_teach.channels import Channel, ScriptedChannel, is_yes
from hermes_teach.metrics import Metrics
from hermes_teach.procedure import (
    PARAM_TYPES,
    Credential,
    Param,
    Procedure,
    ProcedureError,
    evaluate,
    evaluate_value,
    expression_names,
)
from hermes_teach.tiles import TILES, Runtime, TileError, parse_number
from hermes_teach.triggers import Trigger

WF_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")
ROOTS = {"inputs", "trigger", "extract", "steps", "env", "now", "today", "workflow"}
SPECIAL_USES = {"procedure", "workflow"}
EXTRACT_TYPES = ("string", "number", "int", "bool")
MAX_DEPTH = 5


# --- model ---------------------------------------------------------------------
@dataclass
class Extract:
    name: str
    source: str = "trigger.body"
    regex: str = ""
    group: int | str = 1
    type: str = "string"
    default: Any = None
    required: bool = False
    llm: str = ""                 # question for the LLM when there is no regex / no match
    flags: str = "is"             # regex flags: i = ignore case, s = dot matches newline, m = multiline

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"from": self.source}
        for k in ("regex", "llm"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        if self.regex and self.group != 1:
            d["group"] = self.group
        if self.type != "string":
            d["type"] = self.type
        if self.default is not None:
            d["default"] = self.default
        if self.required:
            d["required"] = True
        if self.flags != "is":
            d["flags"] = self.flags
        return d

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any] | str) -> "Extract":
        if isinstance(d, str):
            d = {"from": d}
        t = str(d.get("type", "string"))
        if t not in EXTRACT_TYPES:
            raise ProcedureError(f"extract {name}: unknown type {t}")
        return cls(name=name, source=str(d.get("from", "trigger.body")), regex=str(d.get("regex", "") or ""),
                   group=d.get("group", 1), type=t, default=d.get("default"), required=bool(d.get("required")),
                   llm=str(d.get("llm", "") or ""), flags=str(d.get("flags", "is")))


_STEP_KEYS = {"id", "uses", "if", "needs", "confirm", "confirm_when", "confirm_text", "continue_on_error",
              "always", "outputs", "note", "timeout"}


@dataclass
class WfStep:
    id: str
    uses: str
    config: dict[str, Any] = field(default_factory=dict)   # tile-specific keys (with, run, question, ...)
    if_: str = ""
    needs: list[str] = field(default_factory=list)
    confirm: bool = False
    confirm_when: str = ""
    confirm_text: str = ""
    continue_on_error: bool = False
    always: bool = False               # run even after an earlier step failed or was cancelled (like `if: always()`)
    outputs: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "uses": self.uses}
        d.update(self.config)
        if self.if_:
            d["if"] = self.if_
        if self.needs:
            d["needs"] = list(self.needs)
        if self.confirm:
            d["confirm"] = True
        if self.confirm_when:
            d["confirm_when"] = self.confirm_when
        if self.confirm_text:
            d["confirm_text"] = self.confirm_text
        if self.continue_on_error:
            d["continue_on_error"] = True
        if self.always:
            d["always"] = True
        if self.outputs:
            d["outputs"] = dict(self.outputs)
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any], n: int) -> "WfStep":
        if not isinstance(d, dict) or not d.get("uses"):
            raise ProcedureError(f"step {n}: needs 'uses' (one of {', '.join(sorted(TILES | SPECIAL_USES))})")
        needs = d.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        return cls(
            id=str(d.get("id") or f"step_{n}"), uses=str(d["uses"]),
            config={k: v for k, v in d.items() if k not in _STEP_KEYS},
            if_=str(d.get("if", "") or ""), needs=[str(x) for x in needs],
            confirm=bool(d.get("confirm", False)), confirm_when=str(d.get("confirm_when", "") or ""),
            confirm_text=str(d.get("confirm_text", "") or ""),
            continue_on_error=bool(d.get("continue_on_error", False)), always=bool(d.get("always", False)),
            outputs=dict(d.get("outputs") or {}), note=str(d.get("note", "") or ""),
        )

    def describe(self) -> str:
        c = self.config
        what = c.get("procedure") or c.get("workflow") or c.get("run") or c.get("question") or c.get("text") \
            or c.get("file") or c.get("url") or ""
        return f"{self.id}: {self.uses} {str(what)[:60]}".strip()


@dataclass
class Workflow:
    name: str
    description: str = ""
    version: int = 1
    on: list[Trigger] = field(default_factory=list)
    inputs: dict[str, Param] = field(default_factory=dict)
    credentials: dict[str, Credential] = field(default_factory=dict)
    extract: list[Extract] = field(default_factory=list)
    steps: list[WfStep] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False

    # -- (de)serialization -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "description": self.description, "version": self.version}
        if self.on:
            d["on"] = [t.to_dict() for t in self.on]
        if self.requires_confirmation:
            d["requires_confirmation"] = True
        if self.inputs:
            d["inputs"] = {}
            for p in self.inputs.values():
                pd: dict[str, Any] = {"type": p.type}
                if p.description:
                    pd["description"] = p.description
                if p.default is not None:
                    pd["default"] = p.default
                if p.required:
                    pd["required"] = True
                if p.choices:
                    pd["choices"] = list(p.choices)
                d["inputs"][p.name] = pd
        if self.credentials:
            d["credentials"] = {c.name: {"provider": c.provider, "item": c.item, "fields": list(c.fields)}
                                for c in self.credentials.values()}
        if self.extract:
            d["extract"] = {e.name: e.to_dict() for e in self.extract}
        d["steps"] = [s.to_dict() for s in self.steps]
        if self.outputs:
            d["outputs"] = dict(self.outputs)
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True, width=100)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Workflow":
        if not isinstance(d, dict) or not d.get("name"):
            raise ProcedureError("workflow must be a mapping with a 'name'")
        inputs: dict[str, Param] = {}
        for name, pd in (d.get("inputs") or {}).items():
            pd = pd or {}
            ptype = pd.get("type", "string")
            if ptype not in PARAM_TYPES:
                raise ProcedureError(f"input {name}: unknown type {ptype}")
            inputs[name] = Param(name=name, type=ptype, description=pd.get("description", ""),
                                 default=pd.get("default"), required=bool(pd.get("required", False)),
                                 choices=list(pd.get("choices", [])))
        creds = {}
        for name, cd in (d.get("credentials") or {}).items():
            cd = cd or {}
            creds[name] = Credential(name=name, provider=cd.get("provider", "bitwarden"), item=str(cd.get("item", "")),
                                     fields=list(cd.get("fields", ["username", "password"])))
        on_raw = d.get("on", d.get(True)) or []        # PyYAML reads a bare `on:` key as True
        if isinstance(on_raw, dict):
            on_raw = [{k: v} for k, v in on_raw.items()]
        if isinstance(on_raw, str):
            on_raw = [on_raw]
        wf = cls(
            name=str(d["name"]), description=str(d.get("description", "") or ""), version=int(d.get("version", 1)),
            on=[Trigger.from_dict(t) for t in on_raw], inputs=inputs, credentials=creds,
            extract=[Extract.from_dict(str(k), v) for k, v in (d.get("extract") or {}).items()],
            steps=[WfStep.from_dict(s, i) for i, s in enumerate(d.get("steps") or [], 1)],
            outputs=dict(d.get("outputs") or {}), requires_confirmation=bool(d.get("requires_confirmation", False)),
        )
        wf.validate()
        return wf

    @classmethod
    def from_yaml(cls, text: str) -> "Workflow":
        return cls.from_dict(yaml.safe_load(text))

    @classmethod
    def load(cls, path: str | Path) -> "Workflow":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    # -- validation ---------------------------------------------------------
    def known_names(self) -> set[str]:
        return ROOTS | set(self.inputs) | {e.name for e in self.extract}

    def validate(self) -> None:
        errors: list[str] = []
        if not self.steps:
            errors.append("workflow has no steps")
        for n in list(self.inputs) + [e.name for e in self.extract]:
            if n in ROOTS:
                errors.append(f"'{n}' cannot be used as an input/extract name (reserved)")
        known = self.known_names()
        seen: set[str] = set()
        for i, s in enumerate(self.steps, 1):
            if s.id in seen:
                errors.append(f"step {i}: duplicate id '{s.id}'")
            if s.uses not in TILES and s.uses not in SPECIAL_USES:
                errors.append(f"step {i}: unknown tile '{s.uses}'")
            if s.uses == "procedure" and not s.config.get("procedure"):
                errors.append(f"step {i}: 'procedure' tile needs procedure: <name or path>")
            if s.uses == "workflow" and not s.config.get("workflow"):
                errors.append(f"step {i}: 'workflow' tile needs workflow: <name or path>")
            for need in s.needs:
                if need not in seen:
                    errors.append(f"step {i}: needs '{need}' which is not an earlier step")
            for label, expr in (("if", s.if_), ("confirm_when", s.confirm_when)):
                if expr:
                    errors.extend(f"step {i} {label}: {e}" for e in _check_expr(expr, known))
            errors.extend(f"step {i}: {e}" for e in _check_templates(s.config, known))
            errors.extend(f"step {i} outputs: {e}" for e in _check_templates(s.outputs, known))
            if s.confirm_text:
                errors.extend(f"step {i} confirm_text: {e}" for e in _check_templates(s.confirm_text, known))
            seen.add(s.id)
        for t in self.on:
            if t.config.get("if"):
                errors.extend(f"trigger {t.kind} if: {e}" for e in _check_expr(str(t.config["if"]), known | {"kind"}))
            if t.kind == "email":
                cred = t.config.get("credential")
                if cred and cred not in self.credentials:
                    errors.append(f"trigger email: unknown credential '{cred}'")
        for e in self.extract:
            if e.regex:
                try:
                    re.compile(e.regex)
                except re.error as err:
                    errors.append(f"extract {e.name}: bad regex: {err}")
            if not _lookup_root_ok(e.source, known):
                errors.append(f"extract {e.name}: 'from' must start with one of {sorted(ROOTS)}")
        errors.extend(f"outputs: {e}" for e in _check_templates(self.outputs, known))
        for p in self.inputs.values():
            if p.type == "enum" and not p.choices:
                errors.append(f"input {p.name}: enum without choices")
        if errors:
            raise ProcedureError("; ".join(errors))

    def resolve_inputs(self, given: dict[str, Any]) -> dict[str, Any]:
        unknown = set(given) - set(self.inputs)
        if unknown:
            raise ProcedureError(f"unknown inputs: {sorted(unknown)}")
        out: dict[str, Any] = {}
        for p in self.inputs.values():
            if p.name in given and given[p.name] is not None:
                out[p.name] = p.coerce(given[p.name])
            elif p.default is not None:
                out[p.name] = p.coerce(p.default)
            elif p.required:
                raise ProcedureError(f"missing required input '{p.name}'")
            else:
                out[p.name] = None
        return out


def _lookup_root_ok(path: str, known: set[str]) -> bool:
    return path.split(".", 1)[0] in known


def _check_expr(expr: str, known: set[str]) -> list[str]:
    try:
        roots = expression_names(expr, extended=True)
    except ProcedureError as e:
        return [str(e)]
    bad = sorted(r for r in roots if r not in known)
    if "secret" in bad:
        return ["secrets are not available in workflows; put them in the procedure's credentials"]
    return [f"unknown name(s) {bad} in '{expr}'"] if bad else []


def _check_templates(value: Any, known: set[str]) -> list[str]:
    errors: list[str] = []
    if isinstance(value, str):
        for expr in WF_TEMPLATE_RE.findall(value):
            errors.extend(_check_expr(expr, known))
    elif isinstance(value, dict):
        for v in value.values():
            errors.extend(_check_templates(v, known))
    elif isinstance(value, list):
        for v in value:
            errors.extend(_check_templates(v, known))
    return errors


# --- rendering -----------------------------------------------------------------
def _fmt(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return "" if val is None else str(val)


def render_value(value: Any, ctx: dict[str, Any]) -> Any:
    """Fill ``{{ expr }}`` templates; a string that is one whole template keeps the value's type."""
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    if not isinstance(value, str) or "{{" not in value:
        return value
    whole = WF_TEMPLATE_RE.fullmatch(value.strip())
    if whole:
        return evaluate_value(whole.group(1), ctx, extended=True)
    return WF_TEMPLATE_RE.sub(lambda m: _fmt(evaluate_value(m.group(1), ctx, extended=True)), value)


def lookup(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# --- library -------------------------------------------------------------------
class Library:
    """Finds procedures and workflows by name: ``<dir>/<name>.yaml``, ``<dir>/procedures|workflows/<name>.yaml``,
    ``<skills>/<name>/procedure.yaml|workflow.yaml``, or a path."""

    def __init__(self, dirs: list[str | Path] | None = None, skills_dir: str | Path | None = None) -> None:
        home = Path(os.environ.get("HERMES_TEACH_HOME", Path.home() / ".hermes" / "teach"))
        self.dirs = [Path(d) for d in (dirs if dirs is not None else [Path.cwd(), home])]
        self.skills_dir = Path(skills_dir or os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills"))

    def _find(self, ref: str, kind: str) -> Path:
        p = Path(str(ref)).expanduser()
        if p.suffix in (".yaml", ".yml") and p.exists():
            return p
        candidates = []
        for d in self.dirs:
            for ext in ("yaml", "yml"):
                candidates += [d / f"{ref}.{ext}", d / f"{kind}s" / f"{ref}.{ext}"]
        candidates.append(self.skills_dir / str(ref) / f"{kind}.yaml")
        for c in candidates:
            if c.exists():
                return c
        raise ProcedureError(f"{kind} '{ref}' not found (looked in {', '.join(str(d) for d in self.dirs)}"
                             f" and {self.skills_dir})")

    def procedure(self, ref: str) -> Procedure:
        return Procedure.load(self._find(ref, "procedure"))

    def workflow(self, ref: str) -> Workflow:
        return Workflow.load(self._find(ref, "workflow"))

    def workflows(self) -> list[Path]:
        out: list[Path] = []
        for d in self.dirs:
            out += sorted((d / "workflows").glob("*.y*ml")) if (d / "workflows").is_dir() else []
        if self.skills_dir.is_dir():
            out += sorted(self.skills_dir.glob("*/workflow.yaml"))
        return out


# --- execution -------------------------------------------------------------------
@dataclass
class StepResult:
    id: str
    status: str                       # ok | failed | skipped | cancelled
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    reason: str = ""                  # why skipped
    duration: float = 0.0

    def as_context(self) -> dict[str, Any]:
        return {**self.outputs, "status": self.status, "ok": self.status == "ok",
                "skipped": self.status == "skipped", "error": self.error}


@dataclass
class WfResult:
    status: str                       # ok | failed | cancelled
    steps: list[StepResult] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    extract: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0
    run_id: int | None = None
    run_dir: str = ""

    def step(self, sid: str) -> StepResult | None:
        return next((s for s in self.steps if s.id == sid), None)

    def summary(self) -> str:
        lines = [f"{self.status}" + (f": {self.error}" if self.error else "")]
        for s in self.steps:
            extra = f" ({s.reason})" if s.reason else (f": {s.error}" if s.error else "")
            lines.append(f"  {s.status:9} {s.id}{extra}")
        return "\n".join(lines)


class _Stop(Exception):
    def __init__(self, status: str, error: str = "") -> None:
        super().__init__(error)
        self.status = status
        self.error = error


RunnerFactory = Callable[[Procedure], Any]


class WorkflowRunner:
    def __init__(self, wf: Workflow, *, library: Library | None = None, channel: Channel | None = None,
                 runner_factory: RunnerFactory | None = None, metrics: Metrics | None = None,
                 dry_run: bool = False, log: Callable[[str], None] | None = None,
                 llm_factory: Callable[[], Any] | None = None, runs_dir: str | Path | None = None,
                 depth: int = 0, ask_timeout: float = 3600) -> None:
        self.wf = wf
        self.library = library or Library()
        self.channel = channel or ScriptedChannel(default="yes")
        self.runner_factory = runner_factory
        self.metrics = metrics
        self.dry_run = dry_run
        self.log = log or (lambda _m: None)
        self.llm_factory = llm_factory
        self.runs_dir = Path(runs_dir) if runs_dir else None
        self.depth = depth
        self.ask_timeout = ask_timeout

    # -- context -------------------------------------------------------------
    def _context(self, inputs: dict[str, Any], payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        now = time.localtime()
        ctx: dict[str, Any] = {
            "inputs": inputs, "trigger": payload, "extract": {}, "steps": {}, "env": dict(os.environ),
            "now": time.strftime("%Y-%m-%dT%H:%M:%S", now), "today": time.strftime("%Y-%m-%d", now),
            "workflow": {"name": self.wf.name, "version": self.wf.version, "run_id": run_id, "dry_run": self.dry_run},
        }
        ctx.update(inputs)
        return ctx

    def _extract(self, ctx: dict[str, Any], rt: Runtime) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for e in self.wf.extract:
            raw = lookup(ctx, e.source)
            val: Any = None
            if e.regex and raw is not None:
                flags = 0
                for ch, flag in (("i", re.I), ("s", re.S), ("m", re.M)):
                    flags |= flag if ch in e.flags else 0
                m = re.search(e.regex, str(raw), flags)
                if m:
                    try:
                        val = m.group(e.group) if (m.groups() or e.group == 0) else m.group(0)
                    except (IndexError, re.error):
                        val = m.group(0)
            elif not e.regex and not e.llm:
                val = raw
            if val is None and e.llm and raw is not None and not self.dry_run:
                reply = rt.get_llm().complete(
                    "You extract one value from a text for an automation workflow. Answer with the value only, "
                    "or the single word NONE if it is not there.",
                    f"{e.llm}\n\nText:\n{str(raw)[:8000]}")
                reply = reply.strip().strip("`\"' ")
                val = None if reply.upper() in ("NONE", "") else reply
            if val is None:
                val = e.default
            if val is not None:
                if e.type == "number":
                    val = parse_number(val)
                elif e.type == "int":
                    n = parse_number(val)
                    val = int(n) if n is not None else None
                elif e.type == "bool":
                    val = str(val).strip().lower() in ("1", "true", "yes", "tak", "y", "on")
                else:
                    val = str(val).strip()
            if val is None and e.required:
                raise _Stop("failed", f"could not extract '{e.name}' from {e.source}")
            out[e.name] = val
        return out

    # -- steps ---------------------------------------------------------------
    def _ask_confirm(self, step: WfStep, cfg: dict[str, Any], ctx: dict[str, Any]) -> bool:
        text = render_value(step.confirm_text, ctx) if step.confirm_text else (
            f"Workflow {self.wf.name}, step '{step.describe()}': continue?")
        if self.dry_run:
            self.log(f"would ask: {text}")
            return True
        return is_yes(self.channel.ask(str(text), None, timeout=self.ask_timeout))

    def _run_procedure(self, step: WfStep, cfg: dict[str, Any]) -> dict[str, Any]:
        proc = self.library.procedure(str(cfg["procedure"]))
        params = cfg.get("with") or {}
        if not isinstance(params, dict):
            raise ProcedureError(f"step {step.id}: 'with' must be a mapping of params")
        if self.runner_factory is None:
            raise ProcedureError("no procedure runner configured (drivers)")
        runner = self.runner_factory(proc)
        if step.confirm or step.confirm_when:
            # the workflow author decided when to ask (threshold, always); the user has answered or the
            # case is below the threshold, so the procedure's own confirm steps don't ask again
            runner.confirm = lambda _q: True
        elif not self.dry_run:
            runner.confirm = lambda q: is_yes(self.channel.ask(q, None, timeout=self.ask_timeout))
        res = runner.run({k: v for k, v in params.items() if v is not None}, mode="workflow")
        out = {"status": res.status, "ok": res.status == "ok", "run_id": res.run_id, "executed": res.executed,
               "failed_step": res.failed_step, "error": res.error, "procedure": proc.name}
        if res.status != "ok":
            raise _StepFailed(res.status, res.error or f"procedure {proc.name} {res.status}", out)
        return out

    def _run_workflow(self, step: WfStep, cfg: dict[str, Any]) -> dict[str, Any]:
        if self.depth + 1 >= MAX_DEPTH:
            raise ProcedureError(f"workflows nested deeper than {MAX_DEPTH}")
        child = self.library.workflow(str(cfg["workflow"]))
        inputs = cfg.get("with") or {}
        if not isinstance(inputs, dict):
            raise ProcedureError(f"step {step.id}: 'with' must be a mapping of inputs")
        sub = WorkflowRunner(child, library=self.library, channel=self.channel, runner_factory=self.runner_factory,
                             metrics=self.metrics, dry_run=self.dry_run, log=lambda m: self.log("  " + m),
                             llm_factory=self.llm_factory, runs_dir=self.runs_dir, depth=self.depth + 1,
                             ask_timeout=self.ask_timeout)
        res = sub.run(inputs, cfg.get("payload") if isinstance(cfg.get("payload"), dict) else None)
        out = {**res.outputs, "status": res.status, "ok": res.status == "ok", "error": res.error,
               "workflow": child.name}
        if res.status != "ok":
            raise _StepFailed(res.status, res.error or f"workflow {child.name} {res.status}", out)
        return out

    def run(self, inputs: dict[str, Any] | None = None, payload: dict[str, Any] | None = None,
            mode: str = "run") -> WfResult:
        started = time.time()
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        res = WfResult(status="ok")
        values: dict[str, Any] = {}
        rt = Runtime(channel=self.channel, dry_run=self.dry_run, log=self.log, llm_factory=self.llm_factory,
                     ask_timeout=self.ask_timeout)
        try:
            values = self.wf.resolve_inputs(inputs or {})
            ctx = self._context(values, payload or {}, run_id)
            ctx["extract"] = res.extract = self._extract(ctx, rt)
            ctx.update(res.extract)
            self.log(f"workflow {self.wf.name} v{self.wf.version} run {run_id}"
                     + (" (dry run)" if self.dry_run else ""))
            if self.wf.requires_confirmation and not self.dry_run and not is_yes(
                    self.channel.ask(f"Run workflow '{self.wf.name}' with {values}?", None, timeout=self.ask_timeout)):
                raise _Stop("cancelled", "the user declined")
            stop: _Stop | None = None
            for step in self.wf.steps:
                if stop is not None and not step.always:
                    continue
                sr = self._run_step(step, ctx, rt)
                res.steps.append(sr)
                ctx["steps"][step.id] = sr.as_context()
                if sr.status in ("failed", "cancelled") and not step.continue_on_error and stop is None:
                    stop = _Stop(sr.status, f"step '{step.id}' {sr.status}" + (f": {sr.error}" if sr.error else ""))
            if stop is not None:
                raise stop
            res.outputs = render_value(self.wf.outputs, ctx) if self.wf.outputs else {}
        except _Stop as s:
            res.status, res.error = s.status, s.error
        except (ProcedureError, TileError, Exception) as e:  # noqa: BLE001 - every failure is recorded
            res.status, res.error = "failed", f"{type(e).__name__}: {e}"
        finally:
            res.duration = time.time() - started
            self.log(res.summary())
            if self.runs_dir is not None and not self.dry_run:
                res.run_dir = self._write_run(run_id, values, payload or {}, res)
            if self.metrics is not None and not self.dry_run:
                failed = next((i for i, s in enumerate(res.steps, 1) if s.status in ("failed", "cancelled")), None)
                res.run_id = self.metrics.record(f"workflow:{self.wf.name}", self.wf.version, res.status,
                                                 duration=res.duration, failed_step=failed, error=res.error,
                                                 params={"inputs": values, "extract": res.extract,
                                                         "trigger": _payload_summary(payload or {})},
                                                 mode=mode, started=started)
        return res

    def _run_step(self, step: WfStep, ctx: dict[str, Any], rt: Runtime) -> StepResult:
        t0 = time.time()
        sr = StepResult(id=step.id, status="ok")
        try:
            unmet = [n for n in step.needs if not (ctx["steps"].get(n) or {}).get("ok")]
            if unmet:
                sr.status, sr.reason = "skipped", f"needs {unmet}"
                return sr
            if step.if_ and not evaluate(step.if_, ctx, extended=True):
                sr.status, sr.reason = "skipped", f"if: {step.if_}"
                return sr
            cfg = render_value(step.config, ctx)
            if step.confirm or (step.confirm_when and evaluate(step.confirm_when, ctx, extended=True)):
                if not self._ask_confirm(step, cfg, ctx):
                    sr.status, sr.error = "cancelled", "not confirmed by the user"
                    return sr
            self.log(f"-> {step.describe()}")
            if step.uses == "procedure":
                sr.outputs = self._run_procedure(step, cfg)
            elif step.uses == "workflow":
                sr.outputs = self._run_workflow(step, cfg)
            else:
                sr.outputs = TILES[step.uses](cfg, ctx, rt)
            if step.outputs:
                ctx["steps"][step.id] = sr.as_context()
                sr.outputs.update(render_value(step.outputs, ctx))
        except _StepFailed as f:
            sr.status, sr.error, sr.outputs = f.status, f.error, f.outputs
        except (ProcedureError, TileError) as e:
            sr.status, sr.error = "failed", str(e)
        except Exception as e:  # noqa: BLE001 - tile bugs must not kill the watcher
            sr.status, sr.error = "failed", f"{type(e).__name__}: {e}"
        finally:
            sr.duration = time.time() - t0
        return sr

    def _write_run(self, run_id: str, inputs: dict[str, Any], payload: dict[str, Any], res: WfResult) -> str:
        d = self.runs_dir / self.wf.name / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "run.json").write_text(json.dumps({
            "workflow": self.wf.name, "version": self.wf.version, "run_id": run_id, "status": res.status,
            "error": res.error, "duration": round(res.duration, 2), "inputs": inputs, "extract": res.extract,
            "trigger": _payload_summary(payload), "outputs": res.outputs,
            "steps": [{"id": s.id, "status": s.status, "reason": s.reason, "error": s.error,
                       "duration": round(s.duration, 2), "outputs": _jsonable(s.outputs)} for s in res.steps],
        }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return str(d)


class _StepFailed(Exception):
    def __init__(self, status: str, error: str, outputs: dict[str, Any]) -> None:
        super().__init__(error)
        self.status, self.error, self.outputs = status, error, outputs


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Trigger payload without bulky bodies (kept out of metrics and run records)."""
    return {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
            for k, v in payload.items() if k not in ("html",)}


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(d, default=str, ensure_ascii=False))
