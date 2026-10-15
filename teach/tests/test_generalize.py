import pytest

from hermes_teach.events import Step, Target
from hermes_teach.generalize import heuristic_procedure, llm_generalize, loosen_title
from hermes_teach.procedure import ProcedureError

STEPS = [
    Step("focus", Target(window_title="faktura_7.txt - Notatnik")),
    Step("click", Target(x=10, y=10, element_name="Login", element_role="edit")),
    Step("type", Target(element_name="Login"), text="joe"),
    Step("key", keys=["tab"]),
    Step("type", Target(element_name="Password", window_title="ERP"), sensitive=True),
    Step("type", Target(element_name="Customer name"), text="ACME"),
    Step("click", Target(element_name="Reverse charge", element_role="check_box")),
    Step("hotkey", keys=["ctrl", "s"]),
]


def test_loosen_title():
    assert loosen_title("faktura_7.txt - Notatnik") == "* - Notatnik"
    assert loosen_title("Calculator") == "Calculator"


def test_heuristic_params_credentials_and_checkboxes():
    p = heuristic_procedure(STEPS, "Enter invoice")
    assert p.name == "enter-invoice"
    assert p.steps[0].target.window_title == "* - Notatnik"
    assert "login" not in p.params                      # became the credential username
    assert p.steps[2].text == "{{ secret.erp.username }}"
    assert p.steps[4].text == "{{ secret.erp.password }}" and p.steps[4].sensitive
    assert p.params["customer_name"].default == "ACME"
    assert p.steps[5].text == "{{ customer_name }}"
    assert p.params["reverse_charge"].type == "bool"
    assert p.steps[6].when == "reverse_charge"
    assert p.credentials["erp"].item.startswith("FILL-ME")


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, prompt, image_png=None):
        self.prompts.append(prompt)
        return self.replies.pop(0)


GOOD = """Here you go:
```yaml
name: enter-invoice
description: Enter an invoice
params:
  customer_name: {type: string, default: ACME}
  foreign: {type: bool, default: false}
credentials:
  erp: {provider: bitwarden, item: ERP, fields: [username, password]}
steps:
  - {action: type, text: "{{ secret.erp.username }}"}
  - {action: click, when: foreign, target: {element_name: Reverse charge, element_role: check_box}}
  - action: click
    when: not foreign
    target: {element_name: VAT 23%, element_role: check_box}
    note: "inferred, verify"
```"""


def test_llm_generalize_retries_on_invalid_yaml():
    llm = FakeLLM(["```yaml\nname: x\nsteps:\n  - {action: click, when: ghost}\n```", GOOD])
    draft = heuristic_procedure(STEPS, "Enter invoice")
    p = llm_generalize(llm, STEPS, draft, "foreign suppliers get reverse charge instead of VAT 23%")
    assert p.params["foreign"].type == "bool"
    assert "previous answer was invalid" in llm.prompts[1]
    assert "reverse charge instead" in llm.prompts[0]


def test_llm_generalize_gives_up():
    llm = FakeLLM(["nonsense: [", "still: [bad"])
    with pytest.raises(ProcedureError):
        llm_generalize(llm, STEPS, heuristic_procedure(STEPS, "x"), "")
