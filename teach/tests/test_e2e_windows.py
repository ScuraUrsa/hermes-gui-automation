"""End-to-end on Windows: record real input, generalize, replay, compile to AutoIt and run it.

The "user" is pynput's controller (SendInput), which travels the same path as
a physical keyboard and mouse, so the low-level hooks of the recorder see it.
Runs on GitHub's windows-latest runners and on a real desktop. The AutoIt
part runs when AutoIt3 is installed (CI installs it with Chocolatey).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hermes_teach.events import read_events
from hermes_teach.generalize import heuristic_procedure
from hermes_teach.normalize import normalize
from hermes_teach.procedure import Param, ProcStep
from hermes_teach.secrets import SecretStore

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only"),
]

TITLE = "Hermes Demo Form"


def _interactive_desktop() -> bool:
    """False when the session has no usable input desktop (locked PC, screen off, service)."""
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    return bool(ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))) and bool(
        ctypes.windll.user32.GetForegroundWindow())


def autoit_exe():
    for cand in (shutil.which("AutoIt3_x64.exe"), shutil.which("AutoIt3.exe"),
                 r"C:\Program Files (x86)\AutoIt3\AutoIt3_x64.exe", r"C:\Program Files (x86)\AutoIt3\AutoIt3.exe",
                 r"C:\Program Files\AutoIt3\AutoIt3_x64.exe"):
        if cand and Path(cand).exists():
            return cand
    return None


def start_app(examples, out, pos, tmp_path):
    from hermes_teach.platform import windows as w
    layout = tmp_path / f"layout_{pos.replace('+', '_')}.json"
    proc = subprocess.Popen([sys.executable, str(examples / "demo_form_app.py"), str(out), pos, str(layout)])
    deadline = time.time() + 20
    while not layout.exists() and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.3)
    hwnd = next(x["handle"] for x in w.list_windows() if x["title"] == TITLE)
    w.activate(hwnd)
    time.sleep(0.3)
    return proc, json.loads(layout.read_text())


def test_record_generalize_replay_autoit(tmp_path, examples, monkeypatch):
    from pynput.keyboard import Controller as Kb
    from pynput.keyboard import Key
    from pynput.mouse import Button
    from pynput.mouse import Controller as Mouse

    from hermes_teach.drivers.desktop import DesktopDriver
    from hermes_teach.recorder.desktop import DesktopRecorder
    from hermes_teach.runner import Runner

    if not _interactive_desktop():
        pytest.skip("no interactive desktop (locked screen?): input cannot be recorded or injected")
    kb, mouse = Kb(), Mouse()
    out1 = tmp_path / "recorded_run.json"
    app, lay = start_app(examples, out1, "+100+100", tmp_path)
    rec_path = tmp_path / "rec.jsonl"
    rec = DesktopRecorder(rec_path, window_poll=0.2).start()
    time.sleep(0.5)

    def click(name):
        mouse.position = tuple(lay[name])
        time.sleep(0.1)
        mouse.click(Button.left)
        time.sleep(0.35)

    def type_(text):
        for ch in text:
            kb.type(ch)
            time.sleep(0.03)

    def privacy():
        with kb.pressed(Key.ctrl, Key.shift):
            kb.press(Key.f11)
            kb.release(Key.f11)
        time.sleep(0.2)

    click("name")
    type_("Jan Kowalski")
    click("login")
    type_("jan")
    privacy()
    click("password")
    type_("tajne123")
    privacy()
    click("invoice")
    click("save")
    app.wait(timeout=15)
    time.sleep(0.5)
    rec.stop()

    assert json.loads(out1.read_text()) == {"name": "Jan Kowalski", "login": "jan", "password": "tajne123",
                                            "newsletter": False, "invoice": True}
    assert "tajne123" not in rec_path.read_text(encoding="utf-8")

    steps = normalize(read_events(rec_path))
    actions = [s.action for s in steps]
    assert actions.count("click") == 5 and actions.count("type") == 3, [s.describe() for s in steps]
    proc = heuristic_procedure(steps, "demo form", "Fill the demo form", )
    proc.platforms = ["windows"]
    cred = next(iter(proc.credentials.values()))
    cred.item = "Demo"
    text_param = next(n for n in proc.params if proc.params[n].default == "Jan Kowalski")
    proc.params["invoice"] = Param("invoice", "bool", default=True)
    proc.params["newsletter"] = Param("newsletter", "bool", default=False)
    clicks = [s for s in proc.steps if s.action == "click"]
    invoice_click = clicks[3]
    invoice_click.when = "invoice"
    nl = ProcStep("click", target=type(invoice_click.target)(**{**invoice_click.target.__dict__}),
                  when="newsletter", note="inferred")
    # newsletter sits 140 px left of invoice in the demo layout
    nl.target.off_x = invoice_click.target.off_x - (lay["invoice"][0] - lay["newsletter"][0])
    nl.target.x = nl.target.y = None
    proc.steps.insert(proc.steps.index(invoice_click), nl)
    proc.validate()
    proc.save(tmp_path / "demo.yaml")

    cname = cred.name.upper().replace("-", "_")
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_USERNAME", "anna")
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_PASSWORD", "haslo-xyz")

    out2 = tmp_path / "replay.json"
    app2, _ = start_app(examples, out2, "+420+260", tmp_path)
    runner = Runner(proc, desktop=DesktopDriver(), secrets=SecretStore(proc.credentials, override="env"),
                    confirm=lambda q: True)
    res = runner.run({text_param: "Anna Nowak", "invoice": "false", "newsletter": "true"})
    assert res.status == "ok", res.error
    app2.wait(timeout=15)
    assert json.loads(out2.read_text()) == {"name": "Anna Nowak", "login": "anna", "password": "haslo-xyz",
                                            "newsletter": True, "invoice": False}

    exe = autoit_exe()
    if exe is None:
        pytest.skip("AutoIt3 not installed: replay passed, AutoIt script not executed")
    from hermes_teach.compile import compile_procedure
    script = tmp_path / "demo_form.au3"
    script.write_text(compile_procedure(proc, "autoit"), encoding="utf-8")
    out3 = tmp_path / "autoit.json"
    app3, _ = start_app(examples, out3, "+200+180", tmp_path)
    env = {**os.environ, "HERMES_TEACH_SECRET_PROVIDER": "env"}
    r = subprocess.run([exe, str(script), "--" + text_param, "Ewa Lis", "--invoice", "true",
                        "--newsletter", "true", "--yes"], capture_output=True, text=True, env=env, timeout=90)
    assert r.returncode == 0, (r.stdout, r.stderr)
    app3.wait(timeout=15)
    assert json.loads(out3.read_text()) == {"name": "Ewa Lis", "login": "anna", "password": "haslo-xyz",
                                            "newsletter": True, "invoice": True}
