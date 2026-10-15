import pytest

from hermes_teach.procedure import Procedure, ProcedureError, evaluate, render

YAML = """
name: invoice
description: test
params:
  supplier: {type: string, required: true}
  amount: {type: number, default: 10}
  vat_exempt: {type: bool, default: false}
  payment: {type: enum, choices: [card, transfer], default: transfer}
credentials:
  erp: {provider: env, item: ERP}
steps:
  - action: type
    text: "{{ secret.erp.username }}"
  - action: type
    text: "{{ supplier }} / {{ amount }}"
  - action: click
    when: vat_exempt
    target: {element_name: VAT exempt, element_role: check_box}
  - action: click
    when: "payment == 'card' and amount > 5"
    target: {x: 1, y: 2}
    confirm: true
"""


def test_roundtrip_and_resolve():
    p = Procedure.from_yaml(YAML)
    again = Procedure.from_yaml(p.to_yaml())
    assert again.to_dict() == p.to_dict()
    vals = p.resolve_params({"supplier": "ACME", "vat_exempt": "tak"})
    assert vals == {"supplier": "ACME", "amount": 10.0, "vat_exempt": True, "payment": "transfer"}
    assert render(p.steps[1].text, vals) == "ACME / 10"
    assert p.used_credentials(vals) == {"erp"}


def test_missing_and_bad_params():
    p = Procedure.from_yaml(YAML)
    with pytest.raises(ProcedureError, match="missing required"):
        p.resolve_params({})
    with pytest.raises(ProcedureError, match="not in"):
        p.resolve_params({"supplier": "x", "payment": "cash"})
    with pytest.raises(ProcedureError, match="unknown params"):
        p.resolve_params({"supplier": "x", "nope": 1})


def test_conditions():
    params = {"a": True, "n": 3, "s": "x"}
    assert evaluate("a and n >= 3 and s in ['x', 'y']", params)
    assert not evaluate("not a or s == 'z'", params)
    for bad in ("__import__('os')", "a.b", "s[0]", "n + 1"):
        with pytest.raises(ProcedureError):
            evaluate(bad, params)


def test_validation_catches_bad_refs():
    with pytest.raises(ProcedureError, match="undefined param 'who'"):
        Procedure.from_yaml("name: x\nsteps:\n  - {action: type, text: '{{ who }}'}\n")
    with pytest.raises(ProcedureError, match="unknown credential"):
        Procedure.from_yaml("name: x\nsteps:\n  - {action: type, text: '{{ secret.nope.password }}'}\n")
    with pytest.raises(ProcedureError, match="undefined params"):
        Procedure.from_yaml("name: x\nsteps:\n  - {action: click, when: ghost}\n")
    with pytest.raises(ProcedureError, match="sensitive text"):
        Procedure.from_yaml("name: x\nsteps:\n  - {action: type, text: hunter2, sensitive: true}\n")
    with pytest.raises(ProcedureError, match="unknown action"):
        Procedure.from_yaml("name: x\nsteps:\n  - {action: explode}\n")


def test_extended_expressions_for_workflows():
    from hermes_teach.procedure import evaluate_value, expression_names
    ctx = {"inputs": {"threshold": 500}, "extract": {"amount": 1234.5}, "trigger": {"from": "a@b", "n": None},
           "steps": {"pay": {"ok": True}}}
    assert evaluate("extract.amount > inputs.threshold and steps.pay.ok", ctx, extended=True)
    assert evaluate_value("extract.amount * 2 - 1", ctx, extended=True) == 2468.0
    assert evaluate_value("-inputs.threshold", ctx, extended=True) == -500
    assert evaluate_value("trigger.from", ctx, extended=True) == "a@b"
    assert evaluate_value("trigger.missing.deeper", ctx, extended=True) is None
    assert evaluate_value("steps.nope.ok or 'fallback'", ctx, extended=True) == "fallback"
    assert expression_names("extract.amount > inputs.threshold", extended=True) == {"extract", "inputs"}
    for bad in ("inputs.threshold ** 9", "steps['pay']", "f(1)", "extract.amount.real"):
        with pytest.raises(ProcedureError):
            evaluate_value(bad, ctx, extended=True)
    with pytest.raises(ProcedureError, match="unsupported syntax"):
        evaluate("extract.amount > 1", ctx)          # dotted names stay out of procedure conditions
