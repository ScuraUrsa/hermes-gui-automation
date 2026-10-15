"""From recorded steps to a parameterized procedure.

Two passes:

1. ``heuristic_procedure`` (offline, deterministic): every typed value becomes
   a parameter with the recorded value as default; password fields become a
   Bitwarden credential (and the value typed just before them becomes its
   username); ticked checkboxes become boolean parameters with ``when``;
   window titles are loosened to the application part (``* - Notepad``).
2. ``llm_generalize`` (optional): an LLM gets the steps, the draft and the
   user's description of the variations ("for foreign suppliers tick
   'reverse charge' instead of 'VAT 23%'") and returns an improved YAML,
   which is validated; validation errors are sent back once for a fix.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from hermes_teach.events import Step, Target
from hermes_teach.llm import LLM
from hermes_teach.procedure import Credential, Param, Procedure, ProcedureError, ProcStep

_CHECK_ROLES = {"check_box", "checkbox", "check_box_menu_item", "radio_button", "toggle_button"}


def slug(text: str, fallback: str = "value") -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:32].strip("_")
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    return s


def loosen_title(title: str) -> str:
    """'faktura_12.txt - Notatnik' -> '* - Notatnik'. Titles without a separator stay exact."""
    for sep in (" - ", " — ", " – "):
        if sep in title:
            return "*" + sep + title.rsplit(sep, 1)[1]
    return title


def _field_name(t: Target, n: int, prefix: str) -> str:
    for cand in (t.element_name, t.automation_id):
        if cand:
            return slug(cand, prefix)
    if t.selector:
        m = re.search(r"(?:#|name=\"?|aria-label=\"?|placeholder=\"?|data-testid=\"?)([\w-]+)", t.selector)
        if m:
            return slug(m.group(1), prefix)
    return f"{prefix}_{n}"


def _unique(name: str, taken: set[str]) -> str:
    base, i = name, 2
    while name in taken or name == "secret":
        name, i = f"{base}_{i}", i + 1
    taken.add(name)
    return name


def heuristic_procedure(steps: list[Step], name: str, description: str = "",
                        source_recording: str = "") -> Procedure:
    proc = Procedure(name=slug(name, "procedure").replace("_", "-"), description=description,
                     source_recording=source_recording)
    taken: set[str] = set()
    out: list[ProcStep] = []
    text_n = check_n = 0
    for s in steps:
        ps = ProcStep.from_step(s)
        if ps.target.window_title:
            ps.target.window_title = loosen_title(ps.target.window_title)

        if ps.action in ("type", "browser.fill"):
            if s.sensitive:
                cred = _credential_for(proc, s.target, taken)
                ps.text = f"{{{{ secret.{cred}.password }}}}"
                ps.sensitive = True
                _username_from_previous(out, proc, cred)
            else:
                text_n += 1
                pname = _unique(_field_name(s.target, text_n, "text"), taken)
                proc.params[pname] = Param(pname, "string", default=s.text,
                                           description=f"value typed into {s.target.describe()}")
                ps.text = f"{{{{ {pname} }}}}"
        elif ps.action in ("browser.check", "browser.uncheck") or (
                ps.action == "click" and s.target.element_role in _CHECK_ROLES):
            check_n += 1
            pname = _unique(_field_name(s.target, check_n, "option"), taken)
            proc.params[pname] = Param(pname, "bool", default=True,
                                       description=f"whether to do: {s.describe()}")
            ps.when = pname
        elif ps.action == "browser.select":
            text_n += 1
            pname = _unique(_field_name(s.target, text_n, "choice"), taken)
            proc.params[pname] = Param(pname, "string", default=s.text,
                                       description=f"option chosen in {s.target.describe()}")
            ps.text = f"{{{{ {pname} }}}}"
        out.append(ps)
    proc.steps = out
    proc.validate()
    return proc


def _credential_for(proc: Procedure, t: Target, taken: set[str]) -> str:
    host = re.sub(r"^https?://([^/:]+).*$", r"\1", t.url) if t.url else ""
    if host:
        base = slug(host.split(".")[-2] if host.count(".") >= 1 else host, "login")
    else:
        app = t.process.rsplit(".", 1)[0] or loosen_title(t.window_title).lstrip("* -–—")
        base = slug(app or "login", "login")
    for c in proc.credentials.values():
        if c.item.endswith(f"({host or t.window_title})"):
            return c.name
    cname = _unique(base, taken)
    proc.credentials[cname] = Credential(
        name=cname, provider="bitwarden",
        item=f"FILL-ME: Bitwarden item name ({host or t.window_title})",
        fields=["username", "password"])
    return cname


def _username_from_previous(out: list[ProcStep], proc: Procedure, cred: str) -> None:
    """The text field filled right before a password is almost always the login."""
    for prev in reversed(out[-3:]):
        if prev.action in ("type", "browser.fill") and not prev.sensitive:
            m = re.fullmatch(r"\{\{ (\w+) \}\}", prev.text)
            if m and m.group(1) in proc.params:
                del proc.params[m.group(1)]
                prev.text = f"{{{{ secret.{cred}.username }}}}"
            return


# --- LLM pass ----------------------------------------------------------------
SYSTEM = """You turn recordings of a user's computer actions into reusable, parameterized
procedures (skills) for an automation agent. Output ONLY one YAML document in a ```yaml block.

Format:
name: kebab-case
description: one sentence, what the procedure achieves
version: 1
platforms: [windows, linux]        # keep what the recording implies
requires_confirmation: true|false   # true if the procedure sends, pays, deletes or submits something
params:   {<name>: {type: string|number|int|bool|enum, description, default?, required?, choices?}}
credentials: {<name>: {provider: bitwarden, item: "<Bitwarden item name>", fields: [username, password]}}
steps: list of {action, target?, text?, keys?, button?, count?, dx?, dy?, seconds?, when?,
                confirm?, sensitive?, expect?, note?}

Actions: click, type, key, hotkey, scroll, drag, focus, wait, launch, browser.goto, browser.click,
browser.fill, browser.press, browser.check, browser.uncheck, browser.select, browser.expect_text.
`when` is a Python-like boolean expression over params only (== != < > <= >= in not and or; no calls).
Templates: {{ param }} and {{ secret.<credential>.<field> }}. Never put a literal password in the YAML.

Rules:
- Keep every recorded target field (coordinates, offsets, element names, selectors, window titles):
  the replay engine needs them. You may loosen window titles with * globs.
- Turn values that would change between runs into params with the recorded value as default.
- Where the user's description says a choice depends on a condition, add a param and `when` on the
  alternative steps (you may add steps for alternatives that were not recorded, e.g. clicking another
  checkbox, if the target can be inferred; mark them with note: "inferred, verify").
- Mark irreversible steps (send, submit, pay, delete) with confirm: true.
- Remove accidental noise (stray clicks, duplicated focus steps) but never reorder meaningful steps.
"""


def build_prompt(steps: list[Step], draft: Procedure, user_description: str) -> str:
    return (
        "Recorded steps (JSON):\n" + json.dumps([s.to_dict() for s in steps], ensure_ascii=False, indent=1)
        + "\n\nHeuristic draft procedure:\n```yaml\n" + draft.to_yaml() + "```\n\n"
        + "What the user says about this procedure and how it should vary:\n"
        + (user_description.strip() or "(nothing; generalize sensibly)")
        + "\n\nReturn the improved procedure YAML."
    )


def extract_yaml(text: str) -> dict[str, Any]:
    m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S)
    body = m.group(1) if m else text
    data = yaml.safe_load(body)
    if not isinstance(data, dict):
        raise ProcedureError("LLM did not return a YAML mapping")
    return data


def llm_generalize(llm: LLM, steps: list[Step], draft: Procedure, user_description: str,
                   attempts: int = 2) -> Procedure:
    prompt = build_prompt(steps, draft, user_description)
    last_err = ""
    for _ in range(attempts):
        reply = llm.complete(SYSTEM, prompt if not last_err else
                             prompt + f"\n\nYour previous answer was invalid: {last_err}\nFix it.")
        try:
            proc = Procedure.from_dict(extract_yaml(reply))
            proc.source_recording = draft.source_recording
            return proc
        except (ProcedureError, yaml.YAMLError, TypeError, ValueError) as e:
            last_err = str(e)
    raise ProcedureError(f"LLM could not produce a valid procedure: {last_err}")
