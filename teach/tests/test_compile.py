import py_compile

import pytest

from hermes_teach.compile import auto_target, compile_procedure, python_condition
from hermes_teach.compile.autoit import au3_condition, send_string
from hermes_teach.procedure import Procedure, ProcedureError

DESKTOP = Procedure.from_yaml("""
name: desk
description: demo
params:
  name: {type: string, default: "O'Neil \\"Jr\\""}
  vip: {type: bool, default: false}
  tier: {type: enum, choices: [a, b], default: a}
  n: {type: int, default: 2}
credentials:
  app: {provider: bitwarden, item: "My App"}
steps:
  - {action: focus, target: {window_title: "* - Notepad"}}
  - {action: click, target: {x: 300, y: 200, off_x: 30, off_y: 40, window_title: "* - Notepad"}}
  - {action: type, text: "Hi {{ name }}!"}
  - {action: type, text: "{{ secret.app.password }}", sensitive: true}
  - {action: hotkey, keys: [ctrl, shift, s]}
  - {action: click, when: "vip and tier in ['b'] or n > 3", count: 2, target: {x: 1, y: 2}}
  - {action: key, keys: [enter], confirm: true}
""")

BROWSER = Procedure.from_yaml("""
name: web
params:
  q: {type: string, default: cats}
  safe: {type: bool, default: true}
steps:
  - {action: browser.goto, target: {url: "http://localhost/?x={{ q }}"}}
  - {action: browser.fill, target: {selector: "#q"}, text: "{{ q }}"}
  - {action: browser.check, when: safe, target: {selector: "#safe"}}
  - {action: browser.click, target: {selector: 'button:has-text("Go")'}}
""")


def test_auto_target():
    assert auto_target(BROWSER, "linux") == "playwright"
    assert auto_target(DESKTOP, "windows") == "autoit"
    assert auto_target(DESKTOP, "linux") == "xdotool"


def test_python_scripts_are_valid_python(tmp_path):
    for proc, target in ((BROWSER, "playwright"), (DESKTOP, "xdotool")):
        f = tmp_path / f"{target}.py"
        f.write_text(compile_procedure(proc, target), encoding="utf-8")
        py_compile.compile(str(f), doraise=True)
        assert "s3cr3t" not in f.read_text()


def test_python_condition():
    assert python_condition("vip and tier == 'b'") == "P['vip'] and P['tier'] == 'b'"
    assert python_condition("not true") == "not True"


def test_autoit_output():
    code = compile_procedure(DESKTOP, "autoit")
    assert '_Focus("^.*\\ \\-\\ Notepad$")' in code
    assert '_Click("left", "30", "40", 300, 200, 1)' in code
    assert 'Send("Hi " & $P_name & "!", $SEND_RAW)' in code
    assert 'Send(_Secret("app", "password"), $SEND_RAW)' in code
    assert 'Send("^+s")' in code
    assert "If ((_B($P_vip) And ($P_tier == \"b\")) Or (Number($P_n) > 3)) Then" in code
    assert 'If Not _Confirm("Step 7: key' in code
    assert 'Global $P_name = "O\'Neil ""Jr"""' in code
    assert 'Case "app"\n            Return "My App"' in code


def test_autoit_helpers():
    assert send_string(["alt", "f4"]) == "!{F4}"
    assert send_string(["ctrl", "+"]) == "^{+}"
    assert au3_condition("not vip", DESKTOP) == "Not (_B($P_vip))"
    with pytest.raises(ProcedureError):
        send_string(["ctrl", "weird_key"])


def test_wrong_target_rejected():
    with pytest.raises(ProcedureError):
        compile_procedure(BROWSER, "autoit")
    with pytest.raises(ProcedureError):
        compile_procedure(DESKTOP, "playwright")
