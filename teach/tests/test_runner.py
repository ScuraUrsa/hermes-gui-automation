import json
import os
import stat
import sys

import pytest

from hermes_teach.drivers.base import DryRunDriver
from hermes_teach.metrics import Metrics
from hermes_teach.procedure import Credential, Procedure
from hermes_teach.runner import Runner
from hermes_teach.secrets import BitwardenCLI, SecretError, SecretStore, SecretValue

PROC = Procedure.from_yaml("""
name: login-and-tick
params:
  newsletter: {type: bool, default: false}
  name: {type: string, default: Jan}
credentials:
  portal: {provider: bitwarden, item: Portal}
steps:
  - {action: focus, target: {window_title: "Portal*"}}
  - {action: type, text: "{{ secret.portal.username }}"}
  - {action: key, keys: [tab]}
  - {action: type, text: "{{ secret.portal.password }}", sensitive: true}
  - {action: type, text: "Hello {{ name }}"}
  - {action: click, when: newsletter, target: {x: 5, y: 5, element_name: Newsletter}}
  - {action: click, target: {x: 9, y: 9, element_name: Save}, confirm: true}
""")


@pytest.fixture()
def env_secrets(monkeypatch):
    monkeypatch.setenv("HERMES_SECRET_PORTAL_USERNAME", "jan@example.com")
    monkeypatch.setenv("HERMES_SECRET_PORTAL_PASSWORD", "s3cr3t-pass")


def test_run_with_conditions_secrets_and_redaction(env_secrets, tmp_path):
    d = DryRunDriver()
    d.secret_values = ["s3cr3t-pass", "jan@example.com"]
    m = Metrics(tmp_path / "m.sqlite")
    r = Runner(PROC, desktop=d, secrets=SecretStore(PROC.credentials, override="env"),
               confirm=lambda q: True, metrics=m)
    res = r.run({"newsletter": "yes", "name": "Ola"})
    assert res.status == "ok", res.error
    assert [c[0] for c in d.calls] == ["focus", "type", "press", "type", "type", "click", "click"]
    assert d.calls[4][1]["text"] == "Hello Ola"
    assert all("s3cr3t" not in line for line in res.executed)
    row = m.db.execute("SELECT params FROM runs").fetchone()[0]
    assert "s3cr3t" not in row and json.loads(row)["name"] == "Ola"


def test_condition_false_skips_and_confirm_denied_cancels(env_secrets, tmp_path):
    d = DryRunDriver()
    r = Runner(PROC, desktop=d, secrets=SecretStore(PROC.credentials, override="env"), confirm=lambda q: False)
    res = r.run({})
    assert res.status == "cancelled"
    assert res.skipped == [6]
    assert "click" not in [c[0] for c in d.calls]


def test_locked_bitwarden_fails_before_any_input(monkeypatch, tmp_path):
    monkeypatch.delenv("BW_SESSION", raising=False)
    d = DryRunDriver()
    res = Runner(PROC, desktop=d, confirm=lambda q: True).run({})
    assert res.status == "failed" and "bw unlock" in res.error
    assert d.calls == []


def test_secret_value_is_redacted():
    v = SecretValue("abc")
    assert "abc" not in repr(v) and "abc" not in str(v) and v.reveal() == "abc"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="shell stub")
def test_bitwarden_cli_with_stub(monkeypatch, tmp_path):
    bw = tmp_path / "bw"
    item = {"login": {"username": "u1", "password": "p1", "uris": [{"uri": "https://x"}]},
            "fields": [{"name": "pin", "value": "1234"}]}
    bw.write_text("#!/bin/sh\n"
                  'if [ "$1" = status ]; then echo \'{"status":"unlocked"}\'; exit 0; fi\n'
                  'if [ "$1 $2" = "get item" ]; then echo \'' + json.dumps(item) + "'; exit 0; fi\n"
                  'if [ "$1 $2" = "get totp" ]; then echo 654321; exit 0; fi\n'
                  "exit 1\n")
    bw.chmod(bw.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("BW_SESSION", "x")
    p = BitwardenCLI()
    p.check_ready()
    c = Credential("x", item="X")
    assert [p.get(c, f).reveal() for f in ("username", "password", "uri", "pin", "totp")] == [
        "u1", "p1", "https://x", "1234", "654321"]
    with pytest.raises(SecretError):
        p.get(c, "nope")


def test_metrics_streak_and_promotion(tmp_path):
    m = Metrics(tmp_path / "m.sqlite")
    for _ in range(4):
        m.record("p", 1, "ok", verdict="accepted")
    m.record("p", 1, "ok")                       # pending does not break the streak
    assert m.stats("p", 1).current_streak == 4 and not m.stats("p", 1).candidate
    rid = m.record("p", 1, "ok")
    m.set_verdict(rid, "accepted")
    assert m.stats("p", 1).candidate
    m.record("p", 1, "failed", failed_step=3)
    assert m.stats("p", 1).current_streak == 0
    assert m.failure_hotspots("p", 1) == [(3, 1)]
    for _ in range(5):
        m.record("p", 1, "ok", verdict="accepted")
    m.mark_promoted("p", 1, "playwright", "x.py")
    st = m.stats("p", 1)
    assert st.current_streak == 5 and not st.candidate and st.promoted == ["playwright"]
