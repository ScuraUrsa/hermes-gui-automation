import pytest

from hermes_teach.procedure import Procedure, ProcedureError
from hermes_teach.refine import describe_workflow, diff, draft_workflow, explain_change, llm_edit

PROC = Procedure.from_yaml("""
name: order
version: 3
params:
  qty: {type: int, default: 1}
steps:
  - {action: browser.goto, target: {url: "https://shop.example.com"}}
  - {action: browser.fill, target: {selector: "#qty"}, text: "{{ qty }}"}
  - {action: browser.click, target: {selector: "button:has-text(\\"Dostawa\\")"}}
  - {action: browser.click, target: {selector: "#buy"}, confirm: true}
""")


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, prompt, image_png=None):
        self.prompts.append((system, prompt))
        return self.replies.pop(0)


def test_llm_edit_adds_conditional_alternative_and_bumps_version():
    edited = """```yaml
name: order
version: 99
params:
  qty: {type: int, default: 1}
  country: {type: enum, choices: [PL, DE], default: PL, description: delivery country}
steps:
  - {action: browser.goto, target: {url: "https://shop.example.com"}}
  - {action: browser.fill, target: {selector: "#qty"}, text: "{{ qty }}"}
  - {action: browser.click, target: {selector: "button:has-text(\\"Dostawa\\")"}, when: "country == 'PL'"}
  - action: browser.click
    target: {selector: "button:has-text(\\"Lieferung\\")"}
    when: "country == 'DE'"
    note: "inferred, verify"
  - {action: browser.click, target: {selector: "#buy"}, confirm: true}
```"""
    llm = FakeLLM(["```yaml\nname: order\nsteps:\n  - {action: explode}\n```", edited])
    new = llm_edit(llm, PROC, "jeśli kraj to DE kliknij Lieferung zamiast Dostawa")
    assert new.version == 4 and "country" in new.params and len(new.steps) == 5
    assert "previous answer was invalid" in llm.prompts[1][1] and "unknown action" in llm.prompts[1][1]
    assert "new params: country" in explain_change(PROC, new) and "1 inferred" in explain_change(PROC, new)
    d = diff(PROC.to_yaml(), new.to_yaml())
    assert "+" in d and "Lieferung" in d


def test_llm_edit_gives_up_after_attempts():
    llm = FakeLLM(["nonsense", "more nonsense"])
    with pytest.raises(ProcedureError, match="could not produce"):
        llm_edit(llm, PROC, "x")


def test_draft_workflow_retries_on_unknown_procedure_and_params():
    bad_proc = """```yaml
name: pay
steps:
  - {id: p, uses: procedure, procedure: wire-money, with: {amount: 1}}
```"""
    bad_params = """```yaml
name: pay
steps:
  - {id: p, uses: procedure, procedure: order, with: {quantity: 1}}
```"""
    good = """```yaml
name: pay
description: order when a mail arrives
on:
  - email: {subject: "re:order"}
inputs:
  threshold: {type: number, default: 5}
extract:
  qty: {from: trigger.body, regex: "(\\\\d+) szt", type: int, default: 1}
steps:
  - id: p
    uses: procedure
    procedure: order
    with: {qty: "{{ extract.qty }}"}
    confirm_when: "extract.qty > inputs.threshold"
  - {id: n, uses: notify, text: "ordered {{ extract.qty }}"}
```"""
    llm = FakeLLM([bad_proc, bad_params, good])
    wf = draft_workflow(llm, "zamów, pytaj powyżej 5 sztuk", [PROC], attempts=3)
    assert wf.name == "pay" and wf.steps[0].confirm_when == "extract.qty > inputs.threshold"
    assert "unknown procedures ['wire-money']" in llm.prompts[1][1]
    assert "has no params ['quantity']" in llm.prompts[2][1]
    assert "- order:" in llm.prompts[0][1] and "qty: int=1" in llm.prompts[0][1]
    text = describe_workflow(wf)
    assert "asks when extract.qty > inputs.threshold" in text and "triggers: email" in text
