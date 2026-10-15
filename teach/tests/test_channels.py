import json
import sys
import threading
import time

import pytest

from hermes_teach.channels import (
    ChannelError,
    CommandChannel,
    FileChannel,
    MatrixChannel,
    ScriptedChannel,
    from_env,
    is_yes,
    match_option,
)


def test_match_option_and_is_yes():
    assert match_option("2", ["tak", "nie"]) == "nie"
    assert match_option("NIE", ["tak", "nie"]) == "nie"
    assert match_option("t", ["tak", "nie"]) == "tak"
    assert match_option("x", ["tak", "nie"]) is None
    assert match_option("free text", None) == "free text"
    assert is_yes("Tak") and is_yes("y") and not is_yes("nie") and not is_yes(None)


def test_scripted_channel_records():
    c = ScriptedChannel(answers=["1"], default="no")
    assert c.ask("Q?", ["a", "b"]) == "a" and c.ask("Q2?") == "no"
    c.notify("hi")
    assert c.questions[0] == ("Q?", ["a", "b"]) and c.notices == ["hi"]


def test_command_channel(tmp_path):
    script = tmp_path / "answer.py"
    script.write_text("import json,sys\nq=json.load(sys.stdin)\n"
                      "print('tak' if 'notify' not in q else '')\n"
                      "open(sys.argv[1],'a').write(json.dumps(q)+'\\n')\n")
    log = tmp_path / "log"
    c = CommandChannel(f'"{sys.executable}" "{script}" "{log}"')
    assert c.ask("Pay?", ["tak", "nie"]) == "tak"
    c.notify("done")
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert lines[0]["question"] == "Pay?" and lines[0]["options"] == ["tak", "nie"] and lines[1]["notify"] == "done"
    bad = CommandChannel(f'"{sys.executable}" -c "import sys; sys.exit(2)"')
    with pytest.raises(ChannelError):
        bad.ask("x")


def test_file_channel_roundtrip(tmp_path):
    c = FileChannel(tmp_path, poll=0.05)

    def answer_later():
        for _ in range(100):
            qs = list(tmp_path.glob("*.question.json"))
            if qs:
                q = json.loads(qs[0].read_text())
                (tmp_path / (q["id"] + ".answer")).write_text("2")
                return
            time.sleep(0.02)

    threading.Thread(target=answer_later, daemon=True).start()
    assert c.ask("Which?", ["a", "b"], timeout=5) == "b"
    assert c.ask("Nobody answers", None, timeout=0.2) is None


class FakeMatrix:
    def __init__(self):
        self.sent = []
        self.replies = []          # events returned on the first forward page

    def __call__(self, method, path, body=None, query=None):
        if path.endswith("/account/whoami"):
            return {"user_id": "@hermes:example"}
        if "/send/m.room.message/" in path:
            self.sent.append(body["body"])
            return {"event_id": f"$e{len(self.sent)}"}
        if path.endswith("/messages") and query["dir"] == "b":
            return {"start": "t1", "end": "t0", "chunk": []}
        if path.endswith("/messages") and query["dir"] == "f":
            chunk, self.replies = self.replies, []
            return {"start": query["from"], "end": "t2", "chunk": chunk}
        raise AssertionError((method, path))


def test_matrix_channel_waits_for_allowed_user():
    fake = FakeMatrix()
    c = MatrixChannel("https://matrix.example", "tok", "!room:example", users=["@filip:example"], poll=0.01, http=fake)
    fake.replies = [
        {"type": "m.room.message", "sender": "@hermes:example", "content": {"body": "1"}},      # our own message
        {"type": "m.room.message", "sender": "@someone:example", "content": {"body": "1"}},     # not allowed
        {"type": "m.room.message", "sender": "@filip:example", "content": {"body": "nie"}},
    ]
    assert c.ask("Zapłacić 1200 zł?", ["tak", "nie"], timeout=5) == "nie"
    assert fake.sent[0].startswith("Zapłacić 1200 zł?\n  1. tak\n  2. nie")
    assert c.ask("Nobody?", None, timeout=0.05) is None
    assert "Brak odpowiedzi" in fake.sent[-1]
    c.notify("ok")
    assert fake.sent[-1] == "ok"


def test_from_env_selection(monkeypatch):
    monkeypatch.delenv("HERMES_TEACH_ASK_CMD", raising=False)
    monkeypatch.delenv("HERMES_TEACH_MATRIX_ROOM", raising=False)
    monkeypatch.delenv("HERMES_TEACH_CHANNEL", raising=False)
    assert type(from_env()).__name__ == "ConsoleChannel"
    assert type(from_env(yes=True)).__name__ == "AutoYesChannel"
    monkeypatch.setenv("HERMES_TEACH_ASK_CMD", "echo tak")
    assert type(from_env()).__name__ == "CommandChannel"
    monkeypatch.delenv("HERMES_TEACH_ASK_CMD")
    monkeypatch.setenv("HERMES_TEACH_MATRIX_ROOM", "!r:example")
    with pytest.raises(ChannelError, match="HERMES_TEACH_MATRIX_URL"):
        from_env()
    with pytest.raises(ChannelError, match="unknown channel"):
        from_env("pigeon")
