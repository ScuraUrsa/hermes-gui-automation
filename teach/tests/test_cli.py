from hermes_teach.cli import main
from hermes_teach.events import KEY_DOWN, MOUSE_DOWN, MOUSE_UP, WINDOW, RawEvent, Target, write_events
from hermes_teach.metrics import Metrics
from hermes_teach.procedure import Procedure


def test_generalize_dry_run_metrics_compile(tmp_path, teach_home, capsys, monkeypatch):
    tgt = Target(x=50, y=60, off_x=10, off_y=20, window_title="notes.txt - Editor")
    evs = [RawEvent(0, WINDOW, {}, tgt),
           RawEvent(0.5, MOUSE_DOWN, {"button": "left"}, tgt), RawEvent(0.55, MOUSE_UP, {"button": "left"}, tgt)]
    evs += [RawEvent(1 + i / 10, KEY_DOWN, {"key": c, "char": c}, tgt) for i, c in enumerate("hi")]
    rec = tmp_path / "rec.jsonl"
    write_events(rec, evs)
    out = tmp_path / "proc.yaml"

    assert main(["steps", str(rec)]) == 0
    assert "type 'hi'" in capsys.readouterr().out
    assert main(["generalize", str(rec), "--name", "Notes", "--out", str(out)]) == 0
    proc = Procedure.load(out)
    assert list(proc.params) == ["text_1"]
    assert main(["run", str(out), "--dry-run", "--param", "text_1=bye"]) == 0
    assert "bye" in capsys.readouterr().out

    m = Metrics(teach_home / "metrics.sqlite")
    for _ in range(5):
        m.record("notes", 1, "ok", verdict="accepted")
    m.close()
    assert main(["metrics"]) == 0
    assert "promotion candidate" in capsys.readouterr().out
    script = tmp_path / "notes.py"
    assert main(["compile", str(out), "--target", "xdotool", "--out", str(script)]) == 0
    assert script.exists()
    assert main(["export-skill", str(out), "--dir", str(tmp_path / "skills")]) == 0
    skill = (tmp_path / "skills" / "notes" / "SKILL.md").read_text()
    assert "text_1" in skill and "hermes-teach run" in skill


def test_compile_refuses_without_streak(tmp_path, teach_home):
    out = tmp_path / "p.yaml"
    out.write_text("name: p\nsteps:\n  - {action: key, keys: [enter]}\n")
    assert main(["compile", str(out)]) == 1


def test_workflow_cli_dry_run_trigger_export(tmp_path, teach_home, capsys, examples, monkeypatch):
    import shutil
    lib = tmp_path / "lib"
    (lib / "procedures").mkdir(parents=True)
    (lib / "workflows").mkdir()
    shutil.copy(examples / "procedures" / "bank-transfer.yaml", lib / "procedures")
    shutil.copy(examples / "workflows" / "pay-invoice-from-email.yaml", lib / "workflows")
    wf = str(lib / "workflows" / "pay-invoice-from-email.yaml")
    payload = str(examples / "events" / "invoice-email.json")
    monkeypatch.setenv("HERMES_SECRET_BANK_USERNAME", "jan")
    monkeypatch.setenv("HERMES_SECRET_BANK_PASSWORD", "pw")

    assert main(["workflow", "validate", wf, "--dir", str(lib)]) == 0
    assert "valid (4 steps)" in capsys.readouterr().out
    assert main(["workflow", "show", wf, "--dir", str(lib)]) == 0
    assert "asks when extract.amount > inputs.threshold" in capsys.readouterr().out
    assert main(["workflow", "list", "--dir", str(lib)]) == 0
    assert "pay-invoice-from-email" in capsys.readouterr().out

    log = tmp_path / "pay.csv"
    assert main(["workflow", "trigger", wf, "--dir", str(lib), "--payload", payload, "--dry-run",
                 "--input", f"log_file={log}"]) == 0
    out = capsys.readouterr().out
    assert "1234.56" in out and "would ask" in out and "would append" in out and not log.exists()
    assert "pw" not in out.replace("pay", "")      # dry run never resolves secrets

    # real run through the CLI: --yes answers the threshold question, secrets from env; the browser cannot
    # start (bogus executable), so the pay step fails and the `always` notice reports it
    monkeypatch.setenv("HERMES_TEACH_CHROMIUM", str(tmp_path / "no-such-chromium"))
    assert main(["workflow", "trigger", wf, "--dir", str(lib), "--payload", payload, "--yes",
                 "--secrets-provider", "env", "--input", f"log_file={log}", "--input", "threshold=100"]) == 1
    out = capsys.readouterr().out
    assert "failed    pay" in out and "NOT paid" in out and "(auto)" in out

    assert main(["export-skill", wf, "--dir", str(tmp_path / "skills")]) == 0
    skill = (tmp_path / "skills" / "pay-invoice-from-email" / "SKILL.md").read_text()
    assert "hermes-teach workflow run pay-invoice-from-email" in skill and "asks the user when" in skill
    assert (tmp_path / "skills" / "pay-invoice-from-email" / "workflow.yaml").exists()


def test_ask_cli_through_command_channel(tmp_path, teach_home, capsys, monkeypatch):
    import sys
    monkeypatch.setenv("HERMES_TEACH_ASK_CMD", f'"{sys.executable}" -c "print(2)"')
    assert main(["ask", "Zapłacić?", "--options", "tak,nie", "--channel", "command"]) == 0
    assert '"answer": "nie"' in capsys.readouterr().out
