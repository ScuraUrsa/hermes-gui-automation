"""Procedure (desktop steps) -> AutoIt v3 script for Windows.

Clicks use coordinates relative to the target window (``MouseCoordMode 0``,
same origin as the recorder's ``GetWindowRect`` offsets), window matching uses
``REGEXPTITLE``, text goes through ``Send(..., 1)`` (raw), credentials come
from ``bw get`` at runtime. Run with ``AutoIt3.exe script.au3 --param value``
or compile to .exe with Aut2Exe.
"""

from __future__ import annotations

import ast
import re

from hermes_teach.procedure import DESKTOP_ACTIONS, TEMPLATE_RE, Procedure, ProcedureError

_SEND_KEYS = {
    "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "backspace": "{BS}", "delete": "{DEL}", "insert": "{INS}", "space": "{SPACE}",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}", "home": "{HOME}",
    "end": "{END}", "page_up": "{PGUP}", "page_down": "{PGDN}", "caps_lock": "{CAPSLOCK}",
    "print_screen": "{PRINTSCREEN}", "menu": "{APPSKEY}",
}
_MODS = {"ctrl": "^", "alt": "!", "shift": "+", "cmd": "#", "win": "#"}


def au3_str(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def send_string(keys: list[str]) -> str:
    mods = "".join(_MODS[k] for k in keys[:-1] if k in _MODS)
    last = keys[-1].lower() if keys else ""
    if last in _MODS:                      # a lone modifier
        return {"ctrl": "{CTRL}", "alt": "{ALT}", "shift": "{SHIFT}"}.get(last, "{LWIN}")
    if re.fullmatch(r"f\d{1,2}", last):
        key = "{" + last.upper() + "}"
    elif last in _SEND_KEYS:
        key = _SEND_KEYS[last]
    elif len(last) == 1:
        key = "{" + last + "}" if last in "!#+^{}" else last
    else:
        raise ProcedureError(f"AutoIt: unknown key '{last}'")
    return mods + key


def _template_expr(text: str, proc: Procedure) -> str:
    """'Dear {{ name }}' -> '"Dear " & $P_name' ; secrets -> _Secret("cred", "field")."""
    parts: list[str] = []
    pos = 0
    for m in TEMPLATE_RE.finditer(text):
        if m.start() > pos:
            parts.append(au3_str(text[pos:m.start()]))
        ref = m.group(1)
        if ref.startswith("secret."):
            _, cred, fld = ref.split(".")
            if fld not in ("username", "password", "totp"):
                raise ProcedureError(f"AutoIt target supports username/password/totp fields, not '{fld}'")
            parts.append(f"_Secret({au3_str(cred)}, {au3_str(fld)})")
        else:
            parts.append(f"$P_{ref}")
        pos = m.end()
    if pos < len(text):
        parts.append(au3_str(text[pos:]))
    return " & ".join(parts) if parts else '""'


def au3_condition(expr: str, proc: Procedure) -> str:
    def name(n: str) -> str:
        if n in ("true", "True"):
            return "True"
        if n in ("false", "False"):
            return "False"
        p = proc.params.get(n)
        if p is None:
            raise ProcedureError(f"unknown param {n}")
        if p.type == "bool":
            return f"_B($P_{n})"
        if p.type in ("int", "number"):
            return f"Number($P_{n})"
        return f"$P_{n}"

    def ev(node: ast.AST) -> str:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Name):
            return name(node.id)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "True" if node.value else "False"
            if isinstance(node.value, (int, float)):
                return repr(node.value)
            return au3_str(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"Not ({ev(node.operand)})"
        if isinstance(node, ast.BoolOp):
            op = " And " if isinstance(node.op, ast.And) else " Or "
            return "(" + op.join(ev(v) for v in node.values) + ")"
        if isinstance(node, ast.Compare):
            out, left = [], node.left
            for op, right in zip(node.ops, node.comparators, strict=True):
                lv = ev(left)
                if isinstance(op, (ast.In, ast.NotIn)):
                    if not isinstance(right, (ast.List, ast.Tuple)):
                        raise ProcedureError("AutoIt: 'in' needs a literal list")
                    any_eq = "(" + " Or ".join(f"{lv} == {ev(e)}" for e in right.elts) + ")"
                    out.append(any_eq if isinstance(op, ast.In) else f"Not {any_eq}")
                else:
                    rv = ev(right)
                    sym = {ast.Eq: "==", ast.NotEq: "<>", ast.Lt: "<", ast.LtE: "<=",
                           ast.Gt: ">", ast.GtE: ">="}[type(op)]
                    out.append(f"({lv} {sym} {rv})")
                left = right
            return out[0] if len(out) == 1 else "(" + " And ".join(out) + ")"
        raise ProcedureError(f"AutoIt: unsupported condition syntax {type(node).__name__}")

    return ev(ast.parse(expr, mode="eval"))


def title_regex(pattern: str) -> str:
    if pattern.startswith("re:"):
        return pattern[3:]
    return "^" + "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern) + "$"


PRELUDE = r'''#include <AutoItConstants.au3>
DllCall("user32.dll", "bool", "SetProcessDPIAware")
Opt("WinTitleMatchMode", 4)
Opt("MouseCoordMode", 0)      ; coordinates relative to the active window
Opt("SendKeyDelay", 15)

Global $AUTO_YES = False
'''

FUNCS = r'''
Func _ParseArgs()
    Local $i = 1
    While $i <= $CmdLine[0]
        Local $a = $CmdLine[$i]
        If $a = "--yes" Then
            $AUTO_YES = True
        Else
            If StringLeft($a, 2) = "--" Then $a = StringTrimLeft($a, 2)
            If StringInStr($a, "=") = 0 And $i < $CmdLine[0] Then
                $i += 1
                $a = $a & "=" & $CmdLine[$i]
            EndIf
            Local $eq = StringInStr($a, "=")
            If $eq > 0 Then
                Local $n = StringReplace(StringLeft($a, $eq - 1), "-", "_")
                If Not IsDeclared("P_" & $n) Then
                    ConsoleWriteError("unknown param " & $n & @CRLF)
                    Exit 64
                EndIf
                Assign("P_" & $n, StringTrimLeft($a, $eq), 2)
            EndIf
        EndIf
        $i += 1
    WEnd
EndFunc

Func _Die($msg)
    ConsoleWriteError($msg & @CRLF)
    Exit 64
EndFunc

Func _B($v)
    Return StringInStr("|1|true|yes|y|tak|on|", "|" & StringLower($v) & "|") > 0
EndFunc

Func _Focus($re, $timeout = 10)
    Local $h = WinWait("[REGEXPTITLE:(?i)" & $re & "]", "", $timeout)
    If $h = 0 Then
        ConsoleWriteError("window not found: " & $re & @CRLF)
        Exit 1
    EndIf
    WinActivate($h)
    WinWaitActive($h, "", 5)
    Sleep(150)
EndFunc

Func _Click($btn, $offx, $offy, $absx, $absy, $count)
    If $offx = "" Then
        Opt("MouseCoordMode", 1)
        MouseClick($btn, $absx, $absy, $count, 3)
        Opt("MouseCoordMode", 0)
    Else
        MouseClick($btn, $offx, $offy, $count, 3)
    EndIf
    Sleep(150)
EndFunc

Func _Confirm($q)
    If $AUTO_YES Then Return True
    Return MsgBox(BitOR($MB_YESNO, $MB_ICONQUESTION), "hermes-teach", $q) = $IDYES
EndFunc

Func _Secret($cred, $field)
    Local $item = _CredItem($cred)
    If EnvGet("HERMES_TEACH_SECRET_PROVIDER") = "env" Then
        Return EnvGet("HERMES_SECRET_" & StringUpper(StringReplace($cred, "-", "_")) & "_" & StringUpper($field))
    EndIf
    If EnvGet("BW_SESSION") = "" Then
        MsgBox($MB_ICONERROR, "hermes-teach", "Bitwarden is locked: run 'bw unlock' and set BW_SESSION first.")
        Exit 3
    EndIf
    Local $pid = Run(@ComSpec & ' /c bw get ' & $field & ' "' & $item & '"', "", @SW_HIDE, $STDOUT_CHILD)
    ProcessWaitClose($pid)
    Return StringStripWS(StdoutRead($pid), 3)
EndFunc
'''


def compile_autoit(proc: Procedure) -> str:
    bad = [s.action for s in proc.steps if s.action not in DESKTOP_ACTIONS]
    if bad:
        raise ProcedureError(f"AutoIt target only supports desktop steps, got {sorted(set(bad))}")
    out = [f"; {proc.name} v{proc.version}: {proc.description}",
           "; Compiled by hermes-teach. Usage: AutoIt3.exe this.au3 --param value ... [--yes]",
           "; Credentials are read from Bitwarden at runtime (BW_SESSION must be set).", PRELUDE]
    for p in proc.params.values():
        default = p.default
        if isinstance(default, bool):
            default = "true" if default else "false"
        out.append(f"Global $P_{p.name} = {au3_str('' if default is None else str(default))}"
                   + (f"  ; {p.type}: {p.description}" if p.description else f"  ; {p.type}"))
    out.append("_ParseArgs()")
    for p in proc.params.values():
        if p.required and p.default is None:
            out.append(f'If $P_{p.name} = "" Then _Die("missing --{p.name}")')
        if p.type == "enum":
            choices = "|".join(str(c) for c in p.choices)
            out.append(f'If Not StringInStr("|{choices}|", "|" & $P_{p.name} & "|") Then '
                       f'_Die("--{p.name} must be one of {choices}")')
    out.append("")
    for i, s in enumerate(proc.steps, 1):
        t = s.target
        out.append(f"; {i}. {s.action} {t.describe()}" + (f"  [{s.note}]" if s.note else ""))
        ind = ""
        if s.when:
            out.append(f"If {au3_condition(s.when, proc)} Then")
            ind = "    "
        if s.confirm or (proc.requires_confirmation and i == len(proc.steps)):
            q = f"Step {i}: {s.action} {t.describe()}?"
            out.append(f"{ind}If Not _Confirm({au3_str(q)}) Then Exit 2")
        if s.action == "focus":
            out.append(f"{ind}_Focus({au3_str(title_regex(t.window_title))})")
        elif s.action == "click":
            if t.window_title and i > 1:
                out.append(f"{ind}_Focus({au3_str(title_regex(t.window_title))})")
            ox = "" if t.off_x is None else t.off_x
            oy = "" if t.off_y is None else t.off_y
            out.append(f'{ind}_Click("{s.button}", "{ox}", "{oy}", {t.x or 0}, {t.y or 0}, {s.count})')
        elif s.action == "type":
            out.append(f"{ind}Send({_template_expr(s.text, proc)}, $SEND_RAW)")
        elif s.action in ("key", "hotkey"):
            out.append(f"{ind}Send({au3_str(send_string(s.keys))})")
        elif s.action == "scroll":
            out.append(f'{ind}MouseWheel("{"up" if s.dy > 0 else "down"}", {max(1, abs(s.dy))})')
        elif s.action == "drag":
            out.append(f'{ind}MouseClickDrag("{s.button}", {t.off_x or 0}, {t.off_y or 0}, '
                       f"{(t.off_x or 0) + s.dx}, {(t.off_y or 0) + s.dy})")
        elif s.action == "wait":
            out.append(f"{ind}Sleep({int(s.seconds * 1000)})")
        elif s.action == "launch":
            out.append(f"{ind}Run({_template_expr(s.text, proc)})")
        if s.when:
            out.append("EndIf")
    out.append('ConsoleWrite("OK" & @CRLF)')
    out.append("Exit 0")
    out.append(FUNCS)
    cases = "\n".join(f"        Case {au3_str(c.name)}\n            Return {au3_str(c.item)}"
                      for c in proc.credentials.values())
    out.append("Func _CredItem($cred)\n    Switch $cred\n" + (cases + "\n" if cases else "")
               + "    EndSwitch\n    Return \"\"\nEndFunc\n")
    return "\n".join(out)
