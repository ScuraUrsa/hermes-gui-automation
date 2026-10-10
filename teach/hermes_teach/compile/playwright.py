"""Procedure (browser steps) -> standalone Python Playwright script."""

from __future__ import annotations

from hermes_teach.compile import python_condition
from hermes_teach.compile._pyruntime import prelude
from hermes_teach.procedure import BROWSER_ACTIONS, Procedure, ProcedureError


def _step_code(action: str, sel: str, text_expr: str, keys: list[str], url: str) -> str:
    loc = f"page.locator({sel!r}).first"
    if action == "browser.goto":
        return f"page.goto(render({url!r}, P))"
    if action == "browser.click":
        return f"{loc}.click()"
    if action == "browser.fill":
        return f"{loc}.fill({text_expr})"
    if action == "browser.press":
        key = "+".join(keys)
        return f"{loc}.press({key!r})" if sel else f"page.keyboard.press({key!r})"
    if action == "browser.check":
        return f"{loc}.check()"
    if action == "browser.uncheck":
        return f"{loc}.uncheck()"
    if action == "browser.select":
        return f"{loc}.select_option({text_expr})"
    if action == "browser.expect_text":
        return f"page.get_by_text({text_expr}).first.wait_for(state='visible')"
    raise ProcedureError(f"cannot compile {action} to Playwright")


def compile_playwright(proc: Procedure) -> str:
    bad = [s.action for s in proc.steps if s.action not in BROWSER_ACTIONS]
    if bad:
        raise ProcedureError(f"Playwright target only supports browser steps, got {sorted(set(bad))}")
    body: list[str] = []
    for i, s in enumerate(proc.steps, 1):
        indent = "        "
        body.append(f"{indent}# {i}. {s.action} {s.target.describe()}" + (f"  [{s.note}]" if s.note else ""))
        if s.when:
            body.append(f"{indent}if {python_condition(s.when)}:")
            indent += "    "
        if s.confirm or (proc.requires_confirmation and i == len(proc.steps)):
            body.append(f"{indent}if not confirm({f'Step {i}: {s.action} {s.target.describe()}?'!r}, auto_yes):")
            body.append(f"{indent}    sys.exit('cancelled by user')")
        body.append(indent + _step_code(s.action, s.target.selector, f"render({s.text!r}, P)", s.keys, s.target.url))
    head = (f'#!/usr/bin/env python3\n"""{proc.name} v{proc.version}: {proc.description}\n\n'
            "Compiled by hermes-teach from a procedure that passed its acceptance streak.\n"
            "Usage: python this.py --param value ...   (HEADLESS=1 for no window;\n"
            "HERMES_TEACH_PROFILE=<dir> to keep the browser login between runs)\n"
            'Credentials are read from Bitwarden at runtime (BW_SESSION must be set).\n"""\n')
    run = [
        "",
        "from playwright.sync_api import sync_playwright",
        "",
        "",
        "def run(P, auto_yes=False, headless=False):",
        "    with sync_playwright() as pw:",
        "        opts = {'headless': headless}",
        "        if os.environ.get('HERMES_TEACH_CHROMIUM'):",
        "            opts['executable_path'] = os.environ['HERMES_TEACH_CHROMIUM']",
        "        if os.environ.get('HERMES_TEACH_PROFILE'):",
        "            ctx = pw.chromium.launch_persistent_context(os.environ['HERMES_TEACH_PROFILE'], **opts)",
        "        else:",
        "            ctx = pw.chromium.launch(**opts).new_context()",
        "        ctx.set_default_timeout(15000)",
        "        page = ctx.pages[0] if ctx.pages else ctx.new_page()",
        *body,
        "        ctx.close()",
        "",
        "",
        "if __name__ == '__main__':",
        "    params, yes = parse_params()",
        "    run(params, yes, headless=os.environ.get('HEADLESS') == '1')",
        "    print('OK')",
        "",
    ]
    return head + prelude(proc) + "\n".join(run)
