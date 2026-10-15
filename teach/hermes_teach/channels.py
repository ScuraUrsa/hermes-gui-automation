"""Human-in-the-loop channels: where a run asks the user and reports back.

A workflow stops on ``confirm`` steps, on ``ask`` tiles and whenever
``confirm_when`` is true (for instance an amount above a threshold). The
question goes through a *channel* and the answer comes back the same way:

* ``ConsoleChannel`` — stdin/stdout (interactive terminal);
* ``CommandChannel`` — any command that reads the question as JSON on stdin
  and prints the answer (``HERMES_TEACH_ASK_CMD``), so Hermes, Home Assistant
  or a Telegram bot can forward it;
* ``MatrixChannel`` — posts to a Matrix room (Element X on the phone) and
  waits for a reply from an allowed user (``HERMES_TEACH_MATRIX_URL``,
  ``_TOKEN``, ``_ROOM``, ``_USERS``);
* ``FileChannel`` — drops ``<id>.question.json`` in a directory and waits for
  ``<id>.answer`` (anything that can write a file can answer);
* ``ScriptedChannel`` — canned answers for tests and ``--yes`` runs.

Unanswered questions time out to ``None``; the runner treats that as "no".
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

YES = ("y", "yes", "t", "tak", "ok", "1", "true", "zgoda")
NO = ("n", "no", "nie", "0", "false", "stop")


class ChannelError(RuntimeError):
    pass


class Channel(Protocol):
    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None: ...

    def notify(self, text: str) -> None: ...


def is_yes(answer: str | None) -> bool:
    return bool(answer) and str(answer).strip().lower() in YES


def match_option(answer: str | None, options: list[str] | None) -> str | None:
    """Map a free-text reply onto one of the options (number, prefix or exact, case-insensitive)."""
    if answer is None:
        return None
    a = str(answer).strip()
    if not options:
        return a
    if a.isdigit() and 1 <= int(a) <= len(options):
        return options[int(a) - 1]
    for o in options:
        if o.lower() == a.lower():
            return o
    hits = [o for o in options if o.lower().startswith(a.lower())] if a else []
    return hits[0] if len(hits) == 1 else None


def format_question(question: str, options: list[str] | None) -> str:
    if not options:
        return question
    return question + "\n" + "\n".join(f"  {i}. {o}" for i, o in enumerate(options, 1))


class ScriptedChannel:
    def __init__(self, answers: list[str | None] | None = None, default: str | None = "yes") -> None:
        self.answers = list(answers or [])
        self.default = default
        self.questions: list[tuple[str, list[str] | None]] = []
        self.notices: list[str] = []

    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        self.questions.append((question, options))
        ans = self.answers.pop(0) if self.answers else self.default
        return match_option(ans, options) if options else ans

    def notify(self, text: str) -> None:
        self.notices.append(text)


class ConsoleChannel:
    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        prompt = format_question(question, options) + ("\n> " if options else " [y/N] ")
        try:
            raw = input(prompt)
        except EOFError:
            return None
        return match_option(raw, options) if options else raw.strip()

    def notify(self, text: str) -> None:
        print(text)


class AutoYesChannel(ConsoleChannel):
    """``--yes``: every question is answered with its first option / yes, and printed so the log shows it."""

    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        answer = options[0] if options else "yes"
        print(format_question(question, options) + f"\n> {answer} (auto)")
        return answer


class CommandChannel:
    """``command`` gets ``{"id", "question", "options", "timeout"}`` on stdin, prints the answer.

    ``notify`` sends ``{"id", "notify": text}`` and ignores the output.
    """

    def __init__(self, command: str, timeout: float = 3600) -> None:
        self.command = command
        self.timeout = timeout

    def _call(self, payload: dict[str, Any], timeout: float) -> str:
        try:
            res = subprocess.run(shlex.split(self.command, posix=os.name != "nt"),
                                 input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                                 text=True, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            return ""
        if res.returncode != 0:
            raise ChannelError(f"ask command failed: {res.stderr.strip()[:300]}")
        return res.stdout.strip()

    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        raw = self._call({"id": uuid.uuid4().hex, "question": question, "options": options or [],
                          "timeout": timeout or self.timeout}, timeout)
        if not raw:
            return None
        return match_option(raw, options) if options else raw

    def notify(self, text: str) -> None:
        self._call({"id": uuid.uuid4().hex, "notify": text}, 60)


class FileChannel:
    def __init__(self, directory: str | Path, poll: float = 2.0) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.poll = poll

    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        qid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        (self.dir / f"{qid}.question.json").write_text(
            json.dumps({"id": qid, "question": question, "options": options or []}, ensure_ascii=False),
            encoding="utf-8")
        answer = self.dir / f"{qid}.answer"
        deadline = time.time() + (timeout or 3600)
        while time.time() < deadline:
            if answer.exists():
                raw = answer.read_text(encoding="utf-8").strip()
                return match_option(raw, options) if options else raw
            time.sleep(self.poll)
        return None

    def notify(self, text: str) -> None:
        (self.dir / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ".notify.txt")).write_text(
            text, encoding="utf-8")


class MatrixChannel:
    """Ask in a Matrix room over the plain client-server API (no SDK needed).

    The question is posted as a message; the first reply from one of ``users``
    (any member if the list is empty) after it is the answer. Replies may be
    the option number, its text, or yes/no.
    """

    def __init__(self, homeserver: str, token: str, room: str, users: list[str] | None = None,
                 poll: float = 3.0, http: Callable[..., Any] | None = None) -> None:
        self.base = homeserver.rstrip("/")
        self.token = token
        self.room = room
        self.users = [u for u in (users or []) if u]
        self.poll = poll
        self._http = http or self._urllib
        self.me = ""

    # -- transport ---------------------------------------------------------
    def _urllib(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise ChannelError(f"Matrix {method} {path}: HTTP {e.code} {e.read()[:200]!r}") from None
        except urllib.error.URLError as e:
            raise ChannelError(f"Matrix unreachable: {e.reason}") from None

    def _room(self, suffix: str) -> str:
        return f"/_matrix/client/v3/rooms/{urllib.parse.quote(self.room, safe='')}/{suffix}"

    def _whoami(self) -> str:
        if not self.me:
            self.me = str(self._http("GET", "/_matrix/client/v3/account/whoami").get("user_id", ""))
        return self.me

    def _send(self, text: str) -> str:
        res = self._http("PUT", self._room(f"send/m.room.message/{uuid.uuid4().hex}"),
                         {"msgtype": "m.text", "body": text})
        return str(res.get("event_id", ""))

    # -- channel API ---------------------------------------------------------
    def notify(self, text: str) -> None:
        self._send(text)

    def ask(self, question: str, options: list[str] | None = None, timeout: float = 0) -> str | None:
        me = self._whoami()
        # remember where the room is before asking so only later messages count
        head = self._http("GET", self._room("messages"), query={"dir": "b", "limit": 1})
        since = head.get("start") or ""
        self._send(format_question(question, options) + "\n(odpowiedz numerem, tekstem opcji albo tak/nie)")
        deadline = time.time() + (timeout or 3600)
        token = since
        while time.time() < deadline:
            page = self._http("GET", self._room("messages"), query={"dir": "f", "from": token, "limit": 50})
            for ev in page.get("chunk", []):
                if ev.get("type") != "m.room.message" or ev.get("sender") == me:
                    continue
                if self.users and ev.get("sender") not in self.users:
                    continue
                body = str((ev.get("content") or {}).get("body", "")).strip()
                if not body:
                    continue
                return match_option(body, options) if options else body
            token = page.get("end") or token
            time.sleep(self.poll)
        self._send("Brak odpowiedzi w czasie, krok pominięty.")
        return None


def from_env(name: str | None = None, *, yes: bool = False) -> Channel:
    """Pick the channel: explicit name, else ``HERMES_TEACH_ASK_CMD`` / Matrix env, else console."""
    if yes:
        return AutoYesChannel()
    name = name or os.environ.get("HERMES_TEACH_CHANNEL", "")
    if name == "command" or (not name and os.environ.get("HERMES_TEACH_ASK_CMD")):
        cmd = os.environ.get("HERMES_TEACH_ASK_CMD")
        if not cmd:
            raise ChannelError("HERMES_TEACH_ASK_CMD is not set")
        return CommandChannel(cmd)
    if name == "matrix" or (not name and os.environ.get("HERMES_TEACH_MATRIX_ROOM")):
        url, token, room = (os.environ.get("HERMES_TEACH_MATRIX_URL"), os.environ.get("HERMES_TEACH_MATRIX_TOKEN"),
                            os.environ.get("HERMES_TEACH_MATRIX_ROOM"))
        if not (url and token and room):
            raise ChannelError("set HERMES_TEACH_MATRIX_URL, HERMES_TEACH_MATRIX_TOKEN and HERMES_TEACH_MATRIX_ROOM")
        return MatrixChannel(url, token, room, os.environ.get("HERMES_TEACH_MATRIX_USERS", "").split(","))
    if name == "file":
        return FileChannel(os.environ.get("HERMES_TEACH_ASK_DIR", str(Path.home() / ".hermes" / "teach" / "ask")))
    if name in ("", "console"):
        return ConsoleChannel()
    raise ChannelError(f"unknown channel '{name}'")
