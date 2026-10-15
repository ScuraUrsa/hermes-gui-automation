import json
from pathlib import Path

import pytest

from hermes_teach.channels import ScriptedChannel
from hermes_teach.drivers.base import DryRunDriver
from hermes_teach.metrics import Metrics
from hermes_teach.procedure import Procedure, ProcedureError
from hermes_teach.runner import Runner
from hermes_teach.secrets import SecretStore
from hermes_teach.workflow import Library, Workflow, WorkflowRunner, render_value

TRANSFER = """
name: bank-transfer
params:
  amount: {type: number, required: true}
  account: {type: string, required: true}
  title: {type: string, default: Invoice}
credentials:
  bank: {provider: env, item: Bank}
steps:
  - {action: browser.goto, target: {url: "https://bank.example.com"}}
  - {action: browser.fill, target: {selector: "#login"}, text: "{{ secret.bank.username }}"}
  - {action: browser.fill, target: {selector: "#password"}, text: "{{ secret.bank.password }}", sensitive: true}
  - {action: browser.fill, target: {selector: "#amount"}, text: "{{ amount }}"}
  - {action: browser.fill, target: {selector: "#account"}, text: "{{ account }}"}
  - {action: browser.fill, target: {selector: "#title"}, text: "{{ title }}"}
  - {action: browser.click, target: {selector: "#send"}, confirm: true}
"""

PAY = """
name: pay-invoice
on:
  - email: {from: "*@invoices.example.com", subject: "re:(?i)faktura|invoice"}
  - manual: {}
inputs:
  threshold: {type: number, default: 500}
  log: {type: string, required: true}
extract:
  amount: {from: trigger.body, regex: "(\\\\d[\\\\d ]*[,.]\\\\d{2})\\\\s*(?:zł|PLN)", type: number, required: true}
  account: {from: trigger.body, regex: "\\\\b(\\\\d{2}(?: ?\\\\d{4}){6})\\\\b", required: true}
  title: {from: trigger.subject}
  vat: {from: trigger.body, regex: "VAT (\\\\d+)%", type: int, default: 23}
steps:
  - id: pay
    uses: procedure
    procedure: bank-transfer
    with: {amount: "{{ extract.amount }}", account: "{{ extract.account }}", title: "{{ extract.title }}"}
    confirm_when: "extract.amount > inputs.threshold"
    confirm_text: "Pay {{ extract.amount }} PLN to {{ trigger.from }}?"
  - id: log
    uses: table.append
    needs: [pay]
    file: "{{ inputs.log }}"
    row:
      date: "{{ today }}"
      amount: "{{ extract.amount }}"
      net: "{{ amount / (1 + vat / 100) }}"
      status: "{{ steps.pay.status }}"
  - id: done
    uses: notify
    needs: [log]
    text: "Paid {{ extract.amount }} PLN ({{ steps.log.rows }} rows in log)"
  - id: not_paid
    uses: notify
    always: true
    if: "not steps.pay.ok"
    text: "NOT paid: {{ steps.pay.status }}"
outputs:
  paid: "{{ steps.pay.ok }}"
  amount: "{{ extract.amount }}"
"""

EMAIL = {"kind": "email", "from": "billing@invoices.example.com", "subject": "Faktura 42",
         "body": "Kwota do zapłaty: 1 234,56 zł\nRachunek: 12 1234 5678 9012 3456 7890 1234\nVAT 8%"}


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_SECRET_BANK_USERNAME", "jan")
    monkeypatch.setenv("HERMES_SECRET_BANK_PASSWORD", "pass-123")
    (tmp_path / "procedures").mkdir()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "procedures" / "bank-transfer.yaml").write_text(TRANSFER, encoding="utf-8")
    (tmp_path / "workflows" / "pay-invoice.yaml").write_text(PAY, encoding="utf-8")
    return Library([tmp_path])


class Drivers:
    """Builds dry-run runners and remembers every driver so tests can inspect the calls."""

    def __init__(self):
        self.drivers = []
        self.confirms = []

    def __call__(self, proc: Procedure) -> Runner:
        d = DryRunDriver()
        d.secret_values = ["pass-123"]
        self.drivers.append(d)
        return Runner(proc, desktop=d, browser_factory=lambda: d, secrets=SecretStore(proc.credentials),
                      confirm=lambda q: self.confirms.append(q) or True)


def test_roundtrip_and_plan(lib):
    wf = lib.workflow("pay-invoice")
    again = Workflow.from_yaml(wf.to_yaml())
    assert again.to_dict() == wf.to_dict()
    assert [t.kind for t in wf.on] == ["email", "manual"]
    assert wf.on[0].matches(EMAIL) and not wf.on[0].matches({**EMAIL, "from": "x@spam.example"})
    assert not wf.on[0].matches({**EMAIL, "subject": "Newsletter"})


def test_below_threshold_runs_without_question(lib, tmp_path):
    wf = lib.workflow("pay-invoice")
    chan = ScriptedChannel(answers=[], default=None)         # any question would get "no answer"
    drv = Drivers()
    m = Metrics(tmp_path / "m.sqlite")
    r = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=drv, metrics=m, runs_dir=tmp_path / "runs")
    log = tmp_path / "pay.csv"
    res = r.run({"log": str(log), "threshold": 2000}, EMAIL)
    assert res.status == "ok", res.error
    assert res.extract == {"amount": 1234.56, "account": "12 1234 5678 9012 3456 7890 1234", "title": "Faktura 42",
                           "vat": 8}
    assert chan.questions == []                                # no confirm below the threshold
    assert chan.notices == ["Paid 1234.56 PLN (1 rows in log)"]
    assert [s.status for s in res.steps] == ["ok", "ok", "ok", "skipped"]
    fills = [c[1]["value"] for c in drv.drivers[0].calls if c[0] == "browser.fill"]
    assert fills == ["jan", "***", "1234.56", "12 1234 5678 9012 3456 7890 1234", "Faktura 42"]
    assert drv.confirms == []                                   # workflow decided; procedure confirm auto-passed
    rows = log.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "date,amount,net,status" and rows[1].endswith(",1234.56,1143.111111111111,ok")
    assert res.outputs == {"paid": True, "amount": 1234.56}
    run_json = tmp_path / "runs" / "pay-invoice" / Path(res.run_dir).name / "run.json"
    rec = json.loads(run_json.read_text(encoding="utf-8"))
    assert rec["status"] == "ok" and rec["steps"][0]["outputs"]["procedure"] == "bank-transfer"
    assert "pass-123" not in json.dumps(rec)
    assert m.stats("workflow:pay-invoice", 1).ok == 1
    assert m.stats("bank-transfer", 1).runs == 0           # the test's runner factory passes no metrics


def test_above_threshold_asks_and_no_cancels(lib, tmp_path):
    wf = lib.workflow("pay-invoice")
    chan = ScriptedChannel(answers=["nie"])
    drv = Drivers()
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=drv).run({"log": str(tmp_path / "l.csv")}, EMAIL)
    assert res.status == "cancelled"
    assert chan.questions[0][0] == "Pay 1234.56 PLN to billing@invoices.example.com?"
    assert [s.status for s in res.steps] == ["cancelled", "ok"]  # stops, except the `always` notice
    assert chan.notices == ["NOT paid: cancelled"]
    assert drv.drivers == []                                     # the procedure never started


def test_above_threshold_yes_runs(lib, tmp_path):
    wf = lib.workflow("pay-invoice")
    chan = ScriptedChannel(answers=["tak"])
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=Drivers()).run(
        {"log": str(tmp_path / "l.csv")}, EMAIL)
    assert res.status == "ok", res.error
    assert len(chan.questions) == 1 and res.outputs["paid"] is True


def test_missing_required_extract_fails_before_any_step(lib, tmp_path):
    wf = lib.workflow("pay-invoice")
    drv = Drivers()
    res = WorkflowRunner(wf, library=lib, runner_factory=drv).run({"log": "x.csv"}, {**EMAIL, "body": "no amount"})
    assert res.status == "failed" and "could not extract 'amount'" in res.error
    assert res.steps == [] and drv.drivers == []


def test_failed_procedure_skips_dependents_and_runs_else_branch(lib, tmp_path):
    wf = lib.workflow("pay-invoice")

    def failing(proc):
        r = Drivers()(proc)
        r.desktop = None
        r.browser_factory = None            # no browser driver -> DriverError inside the procedure
        return r

    chan = ScriptedChannel()
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=failing).run(
        {"log": str(tmp_path / "l.csv"), "threshold": 5000}, EMAIL)
    assert res.status == "failed" and res.steps[0].status == "failed"
    assert "no browser driver" in res.steps[0].error
    assert [s.id for s in res.steps] == ["pay", "not_paid"]       # stop at the first failure; `always` still runs
    assert chan.notices == ["NOT paid: failed"]


def test_procedure_confirm_goes_to_channel_unless_workflow_decided(lib, tmp_path):
    wf = Workflow.from_yaml("""
name: plain
steps:
  - id: pay
    uses: procedure
    procedure: bank-transfer
    with: {amount: 10, account: "12 1234 5678 9012 3456 7890 1234"}
""")
    chan = ScriptedChannel(answers=["nie"])
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=Drivers()).run({})
    assert res.status == "cancelled" and res.steps[0].status == "cancelled"
    assert chan.questions and "browser.click" in chan.questions[0][0]      # the procedure's own confirm step
    wf.steps[0].confirm = True                                                # now the workflow asks once up front
    chan = ScriptedChannel(answers=["tak"])
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=Drivers()).run({})
    assert res.status == "ok" and len(chan.questions) == 1


def test_continue_on_error_needs_and_if(tmp_path):
    wf = Workflow.from_yaml("""
name: branches
inputs: {n: {type: int, default: 3}}
steps:
  - {id: a, uses: shell, run: "exit 3", continue_on_error: true}
  - {id: b, uses: set, needs: [a], values: {x: 1}}
  - {id: c, uses: set, if: "not steps.a.ok and n > 2", values: {y: "{{ n * 2 }}", label: "n={{ n }}"}}
  - {id: d, uses: set, values: {z: "{{ steps.c.y + 1 }}"}, outputs: {doubled: "{{ steps.d.z * 2 }}"}}
outputs: {y: "{{ steps.c.y }}", z: "{{ steps.d.doubled }}", label: "{{ steps.c.label }}"}
""")
    res = WorkflowRunner(wf).run({})
    assert res.status == "ok", res.error
    assert [(s.id, s.status) for s in res.steps] == [("a", "failed"), ("b", "skipped"), ("c", "ok"), ("d", "ok")]
    assert res.step("b").reason == "needs ['a']"
    assert res.outputs == {"y": 6, "z": 14, "label": "n=3"}


def test_nested_workflow_and_ask_tile(tmp_path):
    lib_dir = tmp_path
    (lib_dir / "workflows").mkdir()
    (lib_dir / "workflows" / "child.yaml").write_text("""
name: child
inputs: {who: {type: string, required: true}}
steps:
  - {id: greet, uses: set, values: {msg: "hello {{ who }}"}}
outputs: {msg: "{{ steps.greet.msg }}"}
""", encoding="utf-8")
    parent = Workflow.from_yaml("""
name: parent
steps:
  - id: which
    uses: ask
    question: "Who?"
    options: [Ala, Ola]
  - id: sub
    uses: workflow
    workflow: child
    with: {who: "{{ steps.which.answer }}"}
  - {id: say, uses: notify, text: "{{ steps.sub.msg }}!"}
""")
    chan = ScriptedChannel(answers=["2"])
    res = WorkflowRunner(parent, library=Library([lib_dir]), channel=chan).run({})
    assert res.status == "ok", res.error
    assert res.step("which").outputs["answer"] == "Ola" and chan.notices == ["hello Ola!"]


def test_dry_run_executes_nothing_irreversible(lib, tmp_path):
    wf = lib.workflow("pay-invoice")
    marker = tmp_path / "marker"
    wf.steps.insert(0, wf.steps[0].__class__(id="touch", uses="shell", config={"run": f"touch {marker}"}))
    chan = ScriptedChannel(answers=[], default=None)
    logs = []
    res = WorkflowRunner(wf, library=lib, channel=chan, runner_factory=Drivers(), dry_run=True,
                         log=logs.append).run({"log": str(tmp_path / "l.csv")}, EMAIL)
    assert res.status == "ok", res.error
    assert not marker.exists() and not (tmp_path / "l.csv").exists()
    assert chan.questions == [] and any("would ask" in m for m in logs)


def test_requires_confirmation_and_declined(tmp_path):
    wf = Workflow.from_yaml("name: w\nrequires_confirmation: true\nsteps:\n  - {id: s, uses: set, values: {a: 1}}\n")
    res = WorkflowRunner(wf, channel=ScriptedChannel(answers=["no"])).run({})
    assert res.status == "cancelled" and res.steps == []


def test_render_value_types():
    ctx = {"n": 2.5, "s": "x", "steps": {"a": {"ok": True}}, "trigger": {"from": "me@x", "class": "c"}}
    assert render_value("{{ n }}", ctx) == 2.5
    assert render_value("{{ n * 2 }}", ctx) == 5.0
    assert render_value("v={{ n }} {{ steps.a.ok }} {{ trigger.from }} {{ trigger.class }}", ctx) == "v=2.5 true me@x c"
    assert render_value({"a": ["{{ s }}", 1], "b": "{{ steps.missing.ok }}"}, ctx) == {"a": ["x", 1], "b": None}
    assert render_value("plain", ctx) == "plain"


@pytest.mark.parametrize("yaml_text, msg", [
    ("name: w\nsteps: []\n", "no steps"),
    ("name: w\nsteps:\n  - {id: a, uses: teleport}\n", "unknown tile"),
    ("name: w\nsteps:\n  - {id: a, uses: set, values: {x: 1}}\n  - {id: a, uses: set, values: {x: 1}}\n",
     "duplicate id"),
    ("name: w\nsteps:\n  - {id: a, uses: set, needs: [zzz], values: {x: 1}}\n", "not an earlier step"),
    ("name: w\nsteps:\n  - {id: a, uses: set, if: 'ghost > 1', values: {x: 1}}\n", "unknown name"),
    ("name: w\nsteps:\n  - {id: a, uses: set, values: {x: '{{ secret.bank.password }}'}}\n",
     "secrets are not available"),
    ("name: w\nsteps:\n  - {id: a, uses: set, values: {x: '{{ __import__(\"os\") }}'}}\n", "unsupported syntax"),
    ("name: w\nsteps:\n  - {id: a, uses: procedure}\n", "needs procedure"),
    ("name: w\non: [teleport]\nsteps:\n  - {id: a, uses: set, values: {x: 1}}\n", "unknown trigger kind"),
    ("name: w\ninputs: {steps: {type: int}}\nsteps:\n  - {id: a, uses: set, values: {x: 1}}\n", "reserved"),
])
def test_validation(yaml_text, msg):
    with pytest.raises(ProcedureError, match=msg):
        Workflow.from_yaml(yaml_text)


def test_library_lookup_and_missing(lib, tmp_path):
    assert lib.procedure("bank-transfer").name == "bank-transfer"
    assert lib.procedure(str(tmp_path / "procedures" / "bank-transfer.yaml")).name == "bank-transfer"
    assert [p.name for p in lib.workflows()] == ["pay-invoice.yaml"]
    with pytest.raises(ProcedureError, match="not found"):
        lib.procedure("nope")
