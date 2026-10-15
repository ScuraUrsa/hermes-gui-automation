import os
import time

from hermes_teach.triggers import (
    EmailSource,
    Trigger,
    TriggerState,
    parse_email,
    parse_every,
    poll_files,
    schedule_due,
)
from hermes_teach.watch import poll_workflow, watch_once
from hermes_teach.workflow import Library, Workflow, WorkflowRunner

RAW = b"""From: =?utf-8?q?Zak=C5=82ad_Energetyczny?= <billing@invoices.example.com>
To: filip@example.com
Subject: =?utf-8?b?RmFrdHVyYSAyMDI2LzEwLzQy?=
Date: Mon, 12 Oct 2026 08:15:00 +0200
Message-ID: <abc@invoices.example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="B"

--B
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 8bit

Kwota do zap\xc5\x82aty: 1 234,56 z\xc5\x82
--B
Content-Type: application/pdf
Content-Disposition: attachment; filename="faktura.pdf"

%PDF
--B--
"""

HTML_ONLY = b"""From: shop@example.com
Subject: Order
Content-Type: text/html; charset="utf-8"

<html><body><p>Total: <b>99,00 PLN</b></p></body></html>
"""


def test_parse_email_multipart_and_encoded_headers():
    p = parse_email(RAW, uid="7")
    assert p["from"] == "billing@invoices.example.com" and p["from_name"] == "Zakład Energetyczny"
    assert p["subject"] == "Faktura 2026/10/42" and p["uid"] == "7"
    assert p["body"] == "Kwota do zapłaty: 1 234,56 zł" and p["attachments"] == ["faktura.pdf"]
    assert p["date"].startswith("2026-10-12T08:15")


def test_parse_email_html_fallback():
    p = parse_email(HTML_ONLY)
    assert "Total: 99,00 PLN" in p["body"] and "<b>" not in p["body"]


def test_trigger_matches_glob_regex_and_if():
    t = Trigger.from_dict({"email": {"from": "*@invoices.example.com", "subject": "re:faktura|invoice",
                                     "if": "'faktura.pdf' in trigger.attachments"}})
    p = parse_email(RAW)
    assert t.matches(p)
    assert not t.matches({**p, "attachments": []})
    assert not t.matches({**p, "from": "x@other.example"})
    assert Trigger.from_dict("manual").kind == "manual"


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages      # uid -> bytes
        self.stored = []
        self.logged_out = False

    def select(self, folder, readonly=True):
        return ("OK", [b"1"])

    def uid(self, cmd, *args):
        if cmd == "search":
            uids = sorted(self.messages)
            crit = args[1] if len(args) > 1 else "ALL"
            if crit.startswith("UID "):
                lo = int(crit[4:].split(":")[0])
                uids = [u for u in uids if u >= lo]
            return ("OK", [" ".join(map(str, uids)).encode()])
        if cmd == "fetch":
            return ("OK", [(b"1 (RFC822 {n})", self.messages[int(args[0])]), b")"])
        if cmd == "store":
            self.stored.append(args[0])
            return ("OK", [])
        raise AssertionError(cmd)

    def logout(self):
        self.logged_out = True


def test_email_source_polls_by_uid():
    imap = FakeIMAP({3: RAW, 4: HTML_ONLY})
    src = EmailSource("imap.example", "u", lambda: "p", connect=lambda: imap, mark_seen=True)
    msgs, last = src.poll(0)                       # first poll: only the newest message, arms the UID
    assert [m["subject"] for m in msgs] == ["Order"] and last == 4
    imap.messages[5] = RAW
    msgs, last = src.poll(last)
    assert [m["subject"] for m in msgs] == ["Faktura 2026/10/42"] and last == 5
    assert imap.stored == ["4", "5"] and imap.logged_out
    assert src.poll(last) == ([], 5)


def test_poll_files_settle_and_known(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_text("x", encoding="utf-8")
    new, cur = poll_files(tmp_path, "*.pdf", settle=10)
    assert new == [] and cur == set()              # too fresh: wait until it stops changing
    old = time.time() - 60
    os.utime(f, (old, old))
    new, cur = poll_files(tmp_path, "*.pdf", settle=10)
    assert [n["name"] for n in new] == ["a.pdf"] and cur == {str(f.resolve())}
    assert poll_files(tmp_path, "*.pdf", cur, settle=10)[0] == []


def test_schedule_and_state(tmp_path):
    assert parse_every("15m") == 900 and parse_every("2h") == 7200 and parse_every(30) == 30
    assert schedule_due("1h", 0, 10) and not schedule_due("1h", 1000, 1500)
    st = TriggerState(tmp_path / "s.json")
    st.set("k", [1, 2])
    assert TriggerState(tmp_path / "s.json").get("k") == [1, 2]


def test_watch_once_runs_matching_workflow(tmp_path):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "inv.yaml").write_text("""
name: inv
on:
  - email: {host: imap.example, user: u, from: "*@invoices.example.com"}
  - schedule: {every: 1d}
extract:
  amount: {from: trigger.body, regex: "([\\\\d ]+,\\\\d{2}) zł", type: number}
steps:
  - {id: s, uses: set, values: {got: "{{ amount }}"}}
outputs: {got: "{{ steps.s.got }}"}
""", encoding="utf-8")
    lib = Library([tmp_path])
    imap = FakeIMAP({1: HTML_ONLY})
    src = EmailSource("imap.example", "u", lambda: "p", connect=lambda: imap)
    runs = []

    def run(wf, payload):
        res = WorkflowRunner(wf).run({}, payload)
        runs.append(res)
        return res

    logs = []
    state_dir = tmp_path / "state"
    watch_once(lib, run, state_dir, log=logs.append, email_factory=lambda t, w: src)
    assert runs == []                                    # first poll arms UID and schedule only
    imap.messages[2] = RAW
    imap.messages[3] = HTML_ONLY                         # from shop@, filtered out
    watch_once(lib, run, state_dir, log=logs.append, email_factory=lambda t, w: src)
    assert len(runs) == 1 and runs[0].outputs == {"got": 1234.56}
    watch_once(lib, run, state_dir, log=logs.append, email_factory=lambda t, w: src)
    assert len(runs) == 1                                # nothing new
    # the schedule fires once its interval has passed
    wf = Workflow.load(tmp_path / "workflows" / "inv.yaml")
    st = __import__("hermes_teach.triggers", fromlist=["TriggerState"]).TriggerState(state_dir / "inv.json")
    fired = poll_workflow(wf, st, now=time.time() + 90000, email_factory=lambda t, w: src)
    assert [t.kind for t, _ in fired] == ["schedule"]
