"""Event sources that start workflows: e-mail (IMAP), new files, schedules, manual.

Each trigger ``poll()`` returns payloads (plain dicts); the workflow sees one
as ``trigger.*`` (``trigger.subject``, ``trigger.body``, ``trigger.path``...).
Filters on the trigger (``from``, ``subject``, ``glob``...) are glob patterns
or ``re:<regex>`` like window titles elsewhere in hermes-teach, plus an
optional ``if`` expression over the payload.

State (last seen UID, known files, last schedule run) lives in
``<HERMES_TEACH_HOME>/state/<workflow>.json`` so ``watch --once`` can be run
from cron or a systemd timer without re-firing old events.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hermes_teach.platform import title_matches
from hermes_teach.procedure import ProcedureError, evaluate

KINDS = ("manual", "email", "file", "schedule", "webhook")


class TriggerError(RuntimeError):
    pass


@dataclass
class Trigger:
    kind: str
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | str) -> "Trigger":
        if isinstance(d, str):
            d = {d: {}}
        if not isinstance(d, dict) or len(d) != 1:
            raise ProcedureError(f"trigger must be a one-key mapping like 'email: {{...}}', got {d!r}")
        kind, cfg = next(iter(d.items()))
        if kind not in KINDS:
            raise ProcedureError(f"unknown trigger kind '{kind}' (one of {', '.join(KINDS)})")
        return cls(kind=str(kind), config=dict(cfg or {}))

    def to_dict(self) -> dict[str, Any]:
        return {self.kind: dict(self.config)}

    def matches(self, payload: dict[str, Any]) -> bool:
        """Apply the trigger's filters to a payload."""
        for key in ("from", "to", "subject", "name", "glob"):
            pat = self.config.get(key)
            if pat:
                val = str(payload.get("name" if key == "glob" else key, "") or "")
                if not title_matches(str(pat), val):
                    return False
        cond = self.config.get("if")
        if cond and not evaluate(str(cond), {"trigger": payload, **payload}, extended=True):
            return False
        return True


# --- e-mail ------------------------------------------------------------------
def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for raw, enc in email.header.decode_header(value):
        parts.append(raw.decode(enc or "utf-8", "replace") if isinstance(raw, bytes) else raw)
    return "".join(parts)


def parse_email(raw: bytes, uid: str = "") -> dict[str, Any]:
    """RFC822 bytes -> payload with text body, html body and attachment names."""
    msg = email.message_from_bytes(raw)
    text, html, attachments = [], [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        fname = part.get_filename()
        if fname:
            attachments.append(_decode(fname))
            continue
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            s = payload.decode(charset, "replace")
            (text if ctype == "text/plain" else html).append(s)
    body = "\n".join(text).strip()
    if not body and html:
        body = re.sub(r"<[^>]+>", " ", "\n".join(html))
        body = re.sub(r"[ \t]+", " ", body).strip()
    from_name, sender = email.utils.parseaddr(_decode(msg.get("From")))
    sender = sender or _decode(msg.get("From"))
    date = email.utils.parsedate_to_datetime(msg["Date"]).isoformat() if msg.get("Date") else ""
    return {"kind": "email", "uid": uid, "from": sender, "from_name": from_name,
            "to": _decode(msg.get("To")), "subject": _decode(msg.get("Subject")), "date": date,
            "message_id": msg.get("Message-ID", ""), "body": body, "html": "\n".join(html),
            "attachments": attachments}


class EmailSource:
    """Poll an IMAP folder for new messages (by UID, so nothing is seen twice).

    ``password`` is a callable so the secret is fetched only when polling
    (from Bitwarden through the workflow's credentials, or an env var).
    """

    def __init__(self, host: str, user: str, password: Callable[[], str], *, port: int = 993,
                 ssl: bool = True, folder: str = "INBOX", mark_seen: bool = False,
                 connect: Callable[[], Any] | None = None) -> None:
        self.host, self.port, self.ssl, self.user = host, port, ssl, user
        self.password = password
        self.folder = folder
        self.mark_seen = mark_seen
        self._connect = connect

    def _open(self) -> Any:
        if self._connect is not None:
            return self._connect()
        cls = imaplib.IMAP4_SSL if self.ssl else imaplib.IMAP4
        try:
            conn = cls(self.host, self.port)
            conn.login(self.user, self.password())
        except (OSError, imaplib.IMAP4.error) as e:
            raise TriggerError(f"IMAP {self.host}: {e}") from None
        return conn

    def poll(self, last_uid: int = 0) -> tuple[list[dict[str, Any]], int]:
        """New messages with UID > last_uid (first call: only the newest one, to avoid a flood)."""
        conn = self._open()
        try:
            typ, _ = conn.select(self.folder, readonly=not self.mark_seen)
            if typ != "OK":
                raise TriggerError(f"IMAP folder '{self.folder}' not found")
            typ, data = conn.uid("search", None, f"UID {last_uid + 1}:*" if last_uid else "ALL")
            uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
            uids = [u for u in uids if u > last_uid]
            if not last_uid and uids:
                uids = uids[-1:]
            out = []
            for u in uids:
                typ, parts = conn.uid("fetch", str(u), "(RFC822)")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                if raw:
                    out.append(parse_email(raw, str(u)))
                if self.mark_seen:
                    conn.uid("store", str(u), "+FLAGS", "(\\Seen)")
            return out, max([last_uid, *uids])
        finally:
            try:
                conn.logout()
            except Exception:
                pass


# --- files ------------------------------------------------------------------
def poll_files(directory: str | Path, pattern: str = "*", known: set[str] | None = None,
               settle: float = 2.0) -> tuple[list[dict[str, Any]], set[str]]:
    """Files under ``directory`` matching ``pattern`` that were not seen before and are not still being written."""
    d = Path(directory).expanduser()
    known = set(known or ())
    out: list[dict[str, Any]] = []
    now = time.time()
    current: set[str] = set()
    for p in sorted(d.glob(pattern)) if d.is_dir() else []:
        if not p.is_file():
            continue
        key = str(p.resolve())
        current.add(key)
        if key in known:
            continue
        st = p.stat()
        if now - st.st_mtime < settle:
            current.discard(key)          # look again next time
            continue
        out.append({"kind": "file", "path": key, "name": p.name, "size": st.st_size,
                    "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))})
    return out, current


# --- schedule ---------------------------------------------------------------
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_every(spec: str | int | float) -> float:
    """'15m' / '2h' / '1d' / 90 -> seconds."""
    if isinstance(spec, (int, float)):
        return float(spec)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", str(spec))
    if not m:
        raise ProcedureError(f"bad interval '{spec}' (use e.g. 30s, 15m, 2h, 1d)")
    return float(m.group(1)) * _UNITS[m.group(2) or "s"]


def schedule_due(every: str | int | float, last_run: float, now: float | None = None) -> bool:
    """True when ``every`` has passed since ``last_run`` (``last_run`` 0 = never ran = due)."""
    return last_run <= 0 or (now or time.time()) - last_run >= parse_every(every)


# --- state ------------------------------------------------------------------
class TriggerState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
