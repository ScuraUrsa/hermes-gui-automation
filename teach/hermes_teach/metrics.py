"""Run metrics and the "promote to script" policy.

Every run is stored in SQLite with: procedure, version, params (secrets never
included), status (ok / failed / cancelled), which step failed, duration, mode
(llm-guided replay vs compiled script) and the user's verdict (accepted /
rejected / pending). A procedure becomes a *promotion candidate* when its last
``streak`` runs of the current version were all ``ok`` *and* accepted by the
user; the CLI then offers to compile it into a Playwright / AutoIt / xdotool
script. A failure or rejection resets the streak.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STREAK = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure TEXT NOT NULL,
    version INTEGER NOT NULL,
    started REAL NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,            -- ok | failed | cancelled
    failed_step INTEGER,
    error TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    mode TEXT NOT NULL DEFAULT 'replay',  -- replay | script
    verdict TEXT NOT NULL DEFAULT 'pending'  -- accepted | rejected | pending
);
CREATE INDEX IF NOT EXISTS runs_proc ON runs(procedure, version, id);
CREATE TABLE IF NOT EXISTS promotions (
    procedure TEXT NOT NULL,
    version INTEGER NOT NULL,
    target TEXT NOT NULL,            -- playwright | autoit | xdotool
    path TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (procedure, version, target)
);
"""


@dataclass
class Stats:
    procedure: str
    version: int
    runs: int
    ok: int
    accepted: int
    failed: int
    current_streak: int
    avg_duration: float
    candidate: bool
    promoted: list[str]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class Metrics:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def record(self, procedure: str, version: int, status: str, *, duration: float = 0.0,
               failed_step: int | None = None, error: str = "", params: dict[str, Any] | None = None,
               mode: str = "replay", verdict: str = "pending", started: float | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO runs(procedure, version, started, duration, status, failed_step, error,"
            " params, mode, verdict) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (procedure, version, started or time.time(), duration, status, failed_step, error[:500],
             json.dumps(params or {}, default=str), mode, verdict))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def set_verdict(self, run_id: int, verdict: str) -> None:
        if verdict not in ("accepted", "rejected", "pending"):
            raise ValueError(verdict)
        self.db.execute("UPDATE runs SET verdict=? WHERE id=?", (verdict, run_id))
        self.db.commit()

    def last_run_id(self, procedure: str) -> int | None:
        row = self.db.execute("SELECT id FROM runs WHERE procedure=? ORDER BY id DESC LIMIT 1",
                              (procedure,)).fetchone()
        return int(row[0]) if row else None

    def streak(self, procedure: str, version: int) -> int:
        n = 0
        for status, verdict in self.db.execute(
                "SELECT status, verdict FROM runs WHERE procedure=? AND version=? ORDER BY id DESC",
                (procedure, version)):
            if status == "ok" and verdict == "accepted":
                n += 1
            elif status == "ok" and verdict == "pending":
                continue          # not judged yet: neither counts nor breaks the streak
            else:
                break
        return n

    def stats(self, procedure: str, version: int, streak_needed: int = DEFAULT_STREAK) -> Stats:
        row = self.db.execute(
            "SELECT COUNT(*), SUM(status='ok'), SUM(verdict='accepted'), SUM(status='failed'),"
            " AVG(duration) FROM runs WHERE procedure=? AND version=?", (procedure, version)).fetchone()
        promoted = [r[0] for r in self.db.execute(
            "SELECT target FROM promotions WHERE procedure=? AND version=?", (procedure, version))]
        streak = self.streak(procedure, version)
        return Stats(procedure, version, int(row[0] or 0), int(row[1] or 0), int(row[2] or 0),
                     int(row[3] or 0), streak, float(row[4] or 0.0),
                     candidate=streak >= streak_needed and not promoted, promoted=promoted)

    def all_procedures(self) -> list[tuple[str, int]]:
        return [(r[0], int(r[1])) for r in self.db.execute(
            "SELECT DISTINCT procedure, version FROM runs ORDER BY procedure, version")]

    def failure_hotspots(self, procedure: str, version: int) -> list[tuple[int, int]]:
        """(step number, failures) — where the procedure breaks most often."""
        return [(int(r[0]), int(r[1])) for r in self.db.execute(
            "SELECT failed_step, COUNT(*) FROM runs WHERE procedure=? AND version=? AND"
            " failed_step IS NOT NULL GROUP BY failed_step ORDER BY 2 DESC", (procedure, version))]

    def mark_promoted(self, procedure: str, version: int, target: str, path: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO promotions VALUES (?,?,?,?,?)",
                        (procedure, version, target, path, time.time()))
        self.db.commit()
