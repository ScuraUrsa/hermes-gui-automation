"""Procedure (skill) format: parameterized, conditional steps.

A procedure is a YAML document::

    name: register-invoice
    description: Enter a purchase invoice in the ERP
    version: 1
    platforms: [windows, linux]
    params:
      supplier:   {type: string, description: Supplier name}
      amount:     {type: number}
      vat_exempt: {type: bool, default: false}
      payment:    {type: enum, choices: [card, transfer], default: transfer}
    credentials:
      erp: {provider: bitwarden, item: "ERP", fields: [username, password]}
    steps:
      - action: focus
        target: {window_title: "ERP*"}
      - action: type
        text: "{{ secret.erp.username }}"
      - action: click
        when: "vat_exempt"
        target: {element_name: "VAT exempt", element_role: check_box}
      - action: click
        when: "payment == 'card'"
        target: {element_name: "Card", element_role: radio_button}
        confirm: true          # ask the user before this step

``when`` is a small, safe expression language (names, literals, ``== != < >
<= >= in not and or``); no calls, attributes or indexing. Templates are
``{{ param }}`` and ``{{ secret.<credential>.<field> }}``. Secrets are only
resolved at execution time and never written to logs or metrics.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from hermes_teach.events import Step, Target

PARAM_TYPES = ("string", "number", "int", "bool", "enum")
TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")

DESKTOP_ACTIONS = {"click", "type", "key", "hotkey", "scroll", "drag", "focus", "wait", "launch"}
BROWSER_ACTIONS = {"browser.goto", "browser.click", "browser.fill", "browser.press",
                   "browser.check", "browser.uncheck", "browser.select", "browser.expect_text"}
ACTIONS = DESKTOP_ACTIONS | BROWSER_ACTIONS


class ProcedureError(ValueError):
    pass


@dataclass
class Param:
    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    required: bool = False
    choices: list[Any] = field(default_factory=list)

    def coerce(self, value: Any) -> Any:
        if value is None:
            return None
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("1", "true", "yes", "y", "tak", "on"):
                return True
            if s in ("0", "false", "no", "n", "nie", "off", ""):
                return False
            raise ProcedureError(f"param {self.name}: '{value}' is not a boolean")
        if self.type == "int":
            return int(value)
        if self.type == "number":
            return float(value)
        value = str(value)
        if self.type == "enum" and value not in [str(c) for c in self.choices]:
            raise ProcedureError(f"param {self.name}: '{value}' not in {self.choices}")
        return value


@dataclass
class Credential:
    name: str
    provider: str = "bitwarden"     # bitwarden (bw CLI) | bws (Secrets Manager) | env
    item: str = ""                   # Bitwarden item name/id or bws secret id
    fields: list[str] = field(default_factory=lambda: ["username", "password"])


@dataclass
class ProcStep:
    action: str
    target: Target = field(default_factory=Target)
    text: str = ""
    keys: list[str] = field(default_factory=list)
    button: str = "left"
    count: int = 1
    dx: int = 0
    dy: int = 0
    seconds: float = 0.0
    when: str = ""
    confirm: bool = False
    sensitive: bool = False
    expect: dict[str, Any] = field(default_factory=dict)   # e.g. {window_title: "Saved*"}
    note: str = ""
    id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.id:
            d["id"] = self.id
        d["action"] = self.action
        tgt = self.target.to_dict()
        if tgt:
            d["target"] = tgt
        for k in ("text", "keys", "when", "note"):
            v = getattr(self, k)
            if v:
                d[k] = v
        if self.button != "left":
            d["button"] = self.button
        if self.count != 1:
            d["count"] = self.count
        if self.dx or self.dy:
            d["dx"], d["dy"] = self.dx, self.dy
        if self.seconds:
            d["seconds"] = self.seconds
        if self.confirm:
            d["confirm"] = True
        if self.sensitive:
            d["sensitive"] = True
        if self.expect:
            d["expect"] = dict(self.expect)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProcStep":
        if "action" not in d:
            raise ProcedureError(f"step without action: {d}")
        return cls(
            action=str(d["action"]), target=Target.from_dict(d.get("target")),
            text=str(d.get("text", "")), keys=[str(k) for k in d.get("keys", [])],
            button=str(d.get("button", "left")), count=int(d.get("count", 1)),
            dx=int(d.get("dx", 0)), dy=int(d.get("dy", 0)),
            seconds=float(d.get("seconds", 0.0)), when=str(d.get("when", "") or ""),
            confirm=bool(d.get("confirm", False)), sensitive=bool(d.get("sensitive", False)),
            expect=dict(d.get("expect") or {}), note=str(d.get("note", "")), id=str(d.get("id", "")),
        )

    @classmethod
    def from_step(cls, s: Step) -> "ProcStep":
        return cls(action=s.action, target=s.target, text=s.text, keys=list(s.keys),
                   button=s.button, count=s.count, dx=s.dx, dy=s.dy, sensitive=s.sensitive)


@dataclass
class Procedure:
    name: str
    description: str = ""
    version: int = 1
    platforms: list[str] = field(default_factory=lambda: ["windows", "linux"])
    params: dict[str, Param] = field(default_factory=dict)
    credentials: dict[str, Credential] = field(default_factory=dict)
    steps: list[ProcStep] = field(default_factory=list)
    requires_confirmation: bool = False      # ask once before the whole run
    source_recording: str = ""

    # --- (de)serialization -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name, "description": self.description, "version": self.version,
            "platforms": list(self.platforms),
        }
        if self.requires_confirmation:
            d["requires_confirmation"] = True
        if self.source_recording:
            d["source_recording"] = self.source_recording
        if self.params:
            d["params"] = {}
            for p in self.params.values():
                pd: dict[str, Any] = {"type": p.type}
                if p.description:
                    pd["description"] = p.description
                if p.default is not None:
                    pd["default"] = p.default
                if p.required:
                    pd["required"] = True
                if p.choices:
                    pd["choices"] = list(p.choices)
                d["params"][p.name] = pd
        if self.credentials:
            d["credentials"] = {c.name: {"provider": c.provider, "item": c.item, "fields": list(c.fields)}
                                for c in self.credentials.values()}
        d["steps"] = [s.to_dict() for s in self.steps]
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True, width=100)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Procedure":
        if not isinstance(d, dict) or not d.get("name"):
            raise ProcedureError("procedure must be a mapping with a 'name'")
        params = {}
        for name, pd in (d.get("params") or {}).items():
            pd = pd or {}
            ptype = pd.get("type", "string")
            if ptype not in PARAM_TYPES:
                raise ProcedureError(f"param {name}: unknown type {ptype}")
            params[name] = Param(name=name, type=ptype, description=pd.get("description", ""),
                                 default=pd.get("default"), required=bool(pd.get("required", False)),
                                 choices=list(pd.get("choices", [])))
        creds = {}
        for name, cd in (d.get("credentials") or {}).items():
            cd = cd or {}
            creds[name] = Credential(name=name, provider=cd.get("provider", "bitwarden"),
                                     item=str(cd.get("item", "")),
                                     fields=list(cd.get("fields", ["username", "password"])))
        proc = cls(
            name=str(d["name"]), description=str(d.get("description", "")),
            version=int(d.get("version", 1)), platforms=list(d.get("platforms", ["windows", "linux"])),
            params=params, credentials=creds,
            steps=[ProcStep.from_dict(s) for s in d.get("steps") or []],
            requires_confirmation=bool(d.get("requires_confirmation", False)),
            source_recording=str(d.get("source_recording", "")),
        )
        proc.validate()
        return proc

    @classmethod
    def from_yaml(cls, text: str) -> "Procedure":
        return cls.from_dict(yaml.safe_load(text))

    @classmethod
    def load(cls, path: str | Path) -> "Procedure":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    # --- validation --------------------------------------------------------
    def validate(self) -> None:
        errors = []
        names = set(self.params)
        for i, s in enumerate(self.steps, 1):
            if s.action not in ACTIONS:
                errors.append(f"step {i}: unknown action '{s.action}'")
            if s.when:
                try:
                    unknown = expression_names(s.when) - names
                except ProcedureError as e:
                    errors.append(f"step {i}: {e}")
                else:
                    if unknown:
                        errors.append(f"step {i}: condition uses undefined params {sorted(unknown)}")
            for ref in TEMPLATE_RE.findall(s.text):
                if ref.startswith("secret."):
                    parts = ref.split(".")
                    if len(parts) != 3 or parts[1] not in self.credentials:
                        errors.append(f"step {i}: unknown credential reference '{ref}'")
                    elif parts[2] not in self.credentials[parts[1]].fields:
                        errors.append(f"step {i}: credential '{parts[1]}' has no field '{parts[2]}'")
                elif ref not in names:
                    errors.append(f"step {i}: template uses undefined param '{ref}'")
            if s.sensitive and s.text and not TEMPLATE_RE.fullmatch(s.text.strip() or "x"):
                errors.append(f"step {i}: sensitive text must be a secret reference, not a literal")
        for p in self.params.values():
            if p.type == "enum" and not p.choices:
                errors.append(f"param {p.name}: enum without choices")
        if errors:
            raise ProcedureError("; ".join(errors))

    # --- helpers -----------------------------------------------------------
    def resolve_params(self, given: dict[str, Any]) -> dict[str, Any]:
        unknown = set(given) - set(self.params)
        if unknown:
            raise ProcedureError(f"unknown params: {sorted(unknown)}")
        out: dict[str, Any] = {}
        for p in self.params.values():
            if p.name in given:
                out[p.name] = p.coerce(given[p.name])
            elif p.default is not None:
                out[p.name] = p.coerce(p.default)
            elif p.required:
                raise ProcedureError(f"missing required param '{p.name}'")
            else:
                out[p.name] = None
        return out

    def used_credentials(self, params: dict[str, Any]) -> set[str]:
        used = set()
        for s in self.steps:
            if s.when and not evaluate(s.when, params):
                continue
            for ref in TEMPLATE_RE.findall(s.text):
                if ref.startswith("secret."):
                    used.add(ref.split(".")[1])
        return used


# --- safe expression evaluation --------------------------------------------
_ALLOWED = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
            ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple)


def _parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ProcedureError(f"bad condition '{expr}': {e.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ProcedureError(f"condition '{expr}' uses unsupported syntax {type(node).__name__}")
    return tree


def expression_names(expr: str) -> set[str]:
    builtins = {"true", "false", "none", "True", "False", "None"}
    return {n.id for n in ast.walk(_parse(expr)) if isinstance(n, ast.Name)} - builtins


def evaluate(expr: str, params: dict[str, Any]) -> bool:
    tree = _parse(expr)
    consts = {"true": True, "false": False, "none": None, "True": True, "False": False, "None": None}

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in params:
                return params[n.id]
            if n.id in consts:
                return consts[n.id]
            raise ProcedureError(f"unknown name '{n.id}' in condition")
        if isinstance(n, (ast.List, ast.Tuple)):
            return [ev(e) for e in n.elts]
        if isinstance(n, ast.UnaryOp):
            return not ev(n.operand)
        if isinstance(n, ast.BoolOp):
            vals = (ev(v) for v in n.values)
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, right_node in zip(n.ops, n.comparators, strict=True):
                right = ev(right_node)
                ok = _OPS[type(op)](left, right)
                if not ok:
                    return False
                left = right
            return True
        raise ProcedureError(f"unsupported node {type(n).__name__}")

    return bool(ev(tree))


_OPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}


def render(text: str, params: dict[str, Any], secret_lookup: Callable[[str, str], str] | None = None) -> str:
    """Fill ``{{ name }}`` / ``{{ secret.cred.field }}`` placeholders."""

    def sub(m: re.Match[str]) -> str:
        ref = m.group(1)
        if ref.startswith("secret."):
            if secret_lookup is None:
                return "<secret>"
            _, cred, fld = ref.split(".")
            return secret_lookup(cred, fld)
        val = params.get(ref)
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return "" if val is None else str(val)

    return TEMPLATE_RE.sub(sub, text)
