"""End-to-end on Linux/X11: record real input, generalize, replay (moved window), compile, run script.

Needs DISPLAY (Xvfb is fine) with a window manager, xdotool and tkinter.
The "user" is simulated with xdotool, which goes through the same X input
path as a real keyboard and mouse, so the recorder cannot tell the difference.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from hermes_teach.events import read_events
from hermes_teach.generalize import heuristic_procedure
from hermes_teach.normalize import normalize
from hermes_teach.procedure import Param, ProcStep
from hermes_teach.secrets import SecretStore

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only"),
]

TITLE = "Hermes Demo Form"
# widget centres relative to the window's client area (see examples/demo_form_app.py)
NAME, LOGIN, PASSWORD = (190, 25), (190, 65), (190, 105)
NEWSLETTER, INVOICE, SAVE = (30, 145), (170, 145), (175, 203)


def _need():
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        pytest.skip("needs DISPLAY and xdotool")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        pytest.skip("needs tkinter")


def xdo(*args):
    return subprocess.run(["xdotool", *map(str, args)], check=True, capture_output=True, text=True).stdout.strip()


def start_app(examples, out, pos):
    proc = subprocess.Popen([sys.executable, str(examples / "demo_form_app.py"), str(out), pos])
    wid = xdo("search", "--sync", "--onlyvisible", "--name", f"^{TITLE}$").split()[0]
    time.sleep(0.8)
    xdo("windowactivate", "--sync", wid)
    from hermes_teach.platform.linux import window_rect
    rect = window_rect(wid)
    return proc, rect["x"], rect["y"]


def test_record_generalize_replay_compile(tmp_path, examples, monkeypatch):
    _need()
    from hermes_teach.drivers.desktop import DesktopDriver
    from hermes_teach.recorder.desktop import DesktopRecorder
    from hermes_teach.runner import Runner

    # 1. the user does the task once while we record
    out1 = tmp_path / "recorded_run.json"
    app, wx, wy = start_app(examples, out1, "+100+100")
    rec_path = tmp_path / "rec.jsonl"
    rec = DesktopRecorder(rec_path, window_poll=0.2).start()
    time.sleep(0.5)

    def click(pt):
        xdo("mousemove", wx + pt[0], wy + pt[1], "click", 1)
        time.sleep(0.3)

    click(NAME)
    xdo("type", "--delay", 30, "Jan Kowalski")
    click(LOGIN)
    xdo("type", "--delay", 30, "jan")
    xdo("key", "ctrl+shift+F11")          # privacy on: Tk has no accessibility to flag the password field
    click(PASSWORD)
    xdo("type", "--delay", 30, "tajne123")
    xdo("key", "ctrl+shift+F11")
    time.sleep(0.2)
    click(INVOICE)
    click(SAVE)
    app.wait(timeout=10)
    time.sleep(0.5)
    rec.stop()

    assert json.loads(out1.read_text()) == {"name": "Jan Kowalski", "login": "jan", "password": "tajne123",
                                            "newsletter": False, "invoice": True}
    assert "tajne123" not in rec_path.read_text()           # the password never touched the disk

    # 2. normalize + generalize
    steps = normalize(read_events(rec_path))
    actions = [s.action for s in steps]
    assert actions.count("click") == 5 and actions.count("type") == 3, [s.describe() for s in steps]
    proc = heuristic_procedure(steps, "demo form", "Fill the demo form")
    assert any(s.sensitive and "secret." in s.text for s in proc.steps)
    cred = next(iter(proc.credentials.values()))
    cred.item, cred.provider = "Demo", "env"
    text_param = next(n for n in proc.params if proc.params[n].default == "Jan Kowalski")

    # what the user (or the LLM) adds: invoice/newsletter become conditional
    proc.params["invoice"] = Param("invoice", "bool", default=True)
    proc.params["newsletter"] = Param("newsletter", "bool", default=False)
    clicks = [s for s in proc.steps if s.action == "click"]
    invoice_click = clicks[3]
    invoice_click.when = "invoice"
    nl = ProcStep("click", target=type(invoice_click.target)(**{**invoice_click.target.__dict__}),
                  when="newsletter", note="inferred")
    nl.target.off_x, nl.target.off_y = NEWSLETTER
    nl.target.x = nl.target.y = None
    proc.steps.insert(proc.steps.index(invoice_click), nl)
    proc.validate()
    proc.save(tmp_path / "demo.yaml")

    # 3. replay with other parameters, window opened somewhere else
    cname = cred.name.upper().replace("-", "_")
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_USERNAME", "anna")
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_PASSWORD", "haslo-xyz")
    out2 = tmp_path / "replay.json"
    app2, _, _ = start_app(examples, out2, "+420+260")
    runner = Runner(proc, desktop=DesktopDriver(), secrets=SecretStore(proc.credentials), confirm=lambda q: True)
    res = runner.run({text_param: "Anna Nowak", "invoice": "false", "newsletter": "true"})
    assert res.status == "ok", res.error
    app2.wait(timeout=10)
    assert json.loads(out2.read_text()) == {"name": "Anna Nowak", "login": "anna", "password": "haslo-xyz",
                                            "newsletter": True, "invoice": False}

    # 4. compile to a standalone xdotool script and run it with a third parameter set
    from hermes_teach.compile import compile_procedure
    script = tmp_path / "demo_form.py"
    script.write_text(compile_procedure(proc, "xdotool"))
    out3 = tmp_path / "script.json"
    app3, _, _ = start_app(examples, out3, "+200+180")
    env = {**os.environ, "HERMES_TEACH_SECRET_PROVIDER": "env"}
    r = subprocess.run([sys.executable, str(script), "--" + text_param.replace("_", "-"), "Ewa Lis",
                        "--invoice", "true", "--newsletter", "true", "--yes"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    app3.wait(timeout=10)
    assert json.loads(out3.read_text()) == {"name": "Ewa Lis", "login": "anna", "password": "haslo-xyz",
                                            "newsletter": True, "invoice": True}
