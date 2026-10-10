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
