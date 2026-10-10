"""Compile a proven procedure into a standalone script.

Targets:
* ``playwright`` — Python + Playwright, for procedures made only of browser steps;
* ``autoit``     — AutoIt v3 (.au3) for Windows desktop steps;
* ``xdotool``    — Python + xdotool for Linux/X11 desktop steps.

Compiled scripts take the same parameters (``--name value`` / ``name=value``),
evaluate the same ``when`` conditions and read credentials from Bitwarden at
runtime (``bw get ...`` with the user's ``BW_SESSION``); no secret is ever
written into a script. Steps marked ``confirm`` still stop and ask.
"""

from __future__ import annotations

import ast

from hermes_teach.procedure import BROWSER_ACTIONS, DESKTOP_ACTIONS, Procedure, ProcedureError

TARGETS = ("playwright", "autoit", "xdotool")


def auto_target(proc: Procedure, os_name: str) -> str:
    actions = {s.action for s in proc.steps}
    if actions <= BROWSER_ACTIONS:
        return "playwright"
    if actions <= DESKTOP_ACTIONS:
        return "autoit" if os_name == "windows" else "xdotool"
    raise ProcedureError("procedure mixes browser and desktop steps; split it before compiling")


def compile_procedure(proc: Procedure, target: str) -> str:
    if target == "playwright":
        from hermes_teach.compile.playwright import compile_playwright
        return compile_playwright(proc)
    if target == "autoit":
        from hermes_teach.compile.autoit import compile_autoit
        return compile_autoit(proc)
    if target == "xdotool":
        from hermes_teach.compile.xdotool import compile_xdotool
        return compile_xdotool(proc)
    raise ProcedureError(f"unknown compile target '{target}'")


class _ToParamLookup(ast.NodeTransformer):
    CONSTS = {"true": True, "false": False, "none": None, "True": True, "False": False, "None": None}

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.CONSTS:
            return ast.copy_location(ast.Constant(self.CONSTS[node.id]), node)
        return ast.copy_location(
            ast.Subscript(value=ast.Name("P", ast.Load()), slice=ast.Constant(node.id), ctx=ast.Load()), node)


def python_condition(expr: str) -> str:
    """'vat_exempt and payment == "card"' -> 'P["vat_exempt"] and P["payment"] == "card"'."""
    tree = _ToParamLookup().visit(ast.parse(expr, mode="eval"))
    return ast.unparse(ast.fix_missing_locations(tree))
