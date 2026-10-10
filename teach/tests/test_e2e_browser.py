"""End-to-end in the browser: record DOM events, generalize, replay, compile to Playwright."""

import os
import subprocess
import sys

import pytest

from hermes_teach.events import read_events
from hermes_teach.generalize import heuristic_procedure
from hermes_teach.normalize import normalize
from hermes_teach.secrets import SecretStore

pytestmark = pytest.mark.browser


def chromium():
    path = os.environ.get("HERMES_TEACH_CHROMIUM")
    return path or None


@pytest.fixture()
def web():
    pytest.importorskip("playwright.sync_api")
    sys.path.insert(0, os.path.dirname(__file__))
    from webapp import serve
    srv, url, subs = serve()
    yield url, subs
    srv.shutdown()


def test_browser_record_generalize_replay_compile(web, tmp_path, monkeypatch):
    from hermes_teach.drivers.browser import BrowserDriver
    from hermes_teach.recorder.browser import BrowserRecorder
    from hermes_teach.runner import Runner

    url, subs = web
    rec_path = tmp_path / "web.jsonl"
    rec = BrowserRecorder(rec_path, url, headless=True, executable_path=chromium())
    page = rec.start()
    # the "user"
    page.click("#user")
    page.keyboard.type("jan")
    page.click("#pass")
    page.keyboard.type("pw-jan")
    page.click("text=Sign in")
    page.wait_for_url("**/form")
    page.click("[aria-label=Customer]")
    page.keyboard.type("ACME sp. z o.o.")
    page.select_option("select[name=delivery]", "pickup")
    page.check("#express")
    page.click("text=Place order")
    page.wait_for_selector("text=Order saved")
    rec.stop()
    assert subs[-1] == {"customer": "ACME sp. z o.o.", "delivery": "pickup", "express": "on"}
    assert "pw-jan" not in rec_path.read_text()

    steps = normalize(read_events(rec_path))
    assert [s.action for s in steps] == ["browser.goto", "browser.fill", "browser.fill", "browser.click",
                                         "browser.fill", "browser.select", "browser.check", "browser.click"]
    proc = heuristic_procedure(steps, "web order")
    cred = next(iter(proc.credentials.values()))
    cred.item = "Shop"
    proc.save(tmp_path / "web.yaml")
    assert set(proc.params) == {"customer", "delivery", "express"}

    cname = cred.name.upper()
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_USERNAME", "ola")
    monkeypatch.setenv(f"HERMES_SECRET_{cname}_PASSWORD", "pw-ola")
    runner = Runner(proc, secrets=SecretStore(proc.credentials, override="env"), confirm=lambda q: True,
                    browser_factory=lambda: BrowserDriver(headless=True, executable_path=chromium()))
    res = runner.run({"customer": "Kowalski", "delivery": "courier", "express": "false"})
    assert res.status == "ok", res.error
    assert subs[-1] == {"customer": "Kowalski", "delivery": "courier"}

    from hermes_teach.compile import compile_procedure
    script = tmp_path / "web_order.py"
    script.write_text(compile_procedure(proc, "playwright"))
    env = {**os.environ, "HEADLESS": "1", "HERMES_TEACH_SECRET_PROVIDER": "env"}
    if chromium():
        env["HERMES_TEACH_CHROMIUM"] = chromium()
    r = subprocess.run([sys.executable, str(script), "--customer", "Nowak", "--delivery", "pickup",
                        "--express", "yes", "--yes"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert subs[-1] == {"customer": "Nowak", "delivery": "pickup", "express": "on"}
