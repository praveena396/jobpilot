"""Storage for saved resumes, job postings and their analyses.

Uses the same SQLite file as the rest of JobPilot but adds its own tables, and
works with no config file so the analyzer runs standalone. Set `JOBPILOT_DB` to
point somewhere else, or `:memory:` in tests.

Analyses are cached: re-scoring a posting is cheap, but caching means the UI
shows the same numbers it showed yesterday unless the resume changed, which is
what you want when comparing jobs.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jd import JobSpec, parse_job_description
from .match import MatchResult, match
from .resume import Resume, parse_resume

SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    id          INTEGER PRIMARY KEY,
    label       TEXT NOT NULL,
    text        TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS postings (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT 'saved'
                CHECK (stage IN ('saved','applied','screen','interview',
                                 'offer','rejected','withdrawn')),
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS postings_stage ON postings (stage, updated_at DESC);

-- One row per (posting, resume): the cached score and its explanation.
CREATE TABLE IF NOT EXISTS analyses (
    posting_id  INTEGER NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    resume_id   INTEGER NOT NULL REFERENCES resumes (id) ON DELETE CASCADE,
    score       INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (posting_id, resume_id)
);

-- Every stage change, so the funnel can be measured later.
CREATE TABLE IF NOT EXISTS stage_events (
    id          INTEGER PRIMARY KEY,
    posting_id  INTEGER NOT NULL REFERENCES postings (id) ON DELETE CASCADE,
    from_stage  TEXT,
    to_stage    TEXT NOT NULL,
    at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

STAGES = ("saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn")
ACTIVE_STAGES = ("saved", "applied", "screen", "interview")


class NotFoundError(KeyError):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def default_db_path() -> str:
    """`JOBPILOT_DB`, else the configured path, else data/jobpilot.db."""
    env = os.environ.get("JOBPILOT_DB")
    if env:
        return env
    try:  # the rest of JobPilot keeps its path in config; use it when present
        from jobpilot import get, get_root
        p = Path(get("database.path", "data/jobpilot.db"))
        return str(p if p.is_absolute() else get_root() / p)
    except Exception:  # no config file: fall back to a sensible default
        return str(Path(__file__).resolve().parents[2] / "data" / "jobpilot.db")


@dataclass
class Store:
    """Thin data layer. One `Store` owns one connection."""

    conn: sqlite3.Connection

    @classmethod
    def open(cls, path: str | None = None) -> Store:
        target = path or default_db_path()
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    # ---------------- resumes ----------------
    def add_resume(self, label: str, text: str, make_active: bool = True) -> int:
        cur = self.conn.execute("INSERT INTO resumes (label, text) VALUES (?, ?)", (label, text))
        rid = int(cur.lastrowid or 0)
        if make_active:
            self.set_active_resume(rid)
        self.conn.commit()
        return rid

    def set_active_resume(self, resume_id: int) -> None:
        if self.conn.execute("SELECT 1 FROM resumes WHERE id = ?", (resume_id,)).fetchone() is None:
            raise NotFoundError(f"resume {resume_id}")
        self.conn.execute("UPDATE resumes SET is_active = 0")
        self.conn.execute("UPDATE resumes SET is_active = 1 WHERE id = ?", (resume_id,))
        self.conn.commit()

    def active_resume(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def get_resume(self, resume_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"resume {resume_id}")
        return dict(row)

    def list_resumes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, label, is_active, created_at, length(text) AS size "
            "FROM resumes ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_resume(self, resume_id: int) -> None:
        self.conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
        self.conn.commit()

    # ---------------- postings ----------------
    def add_posting(self, text: str, title: str = "", company: str = "", location: str = "",
                    url: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO postings (title, company, location, url, text) VALUES (?, ?, ?, ?, ?)",
            (title.strip(), company.strip(), location.strip(), url.strip(), text))
        pid = int(cur.lastrowid or 0)
        self.conn.execute("INSERT INTO stage_events (posting_id, from_stage, to_stage) "
                          "VALUES (?, NULL, 'saved')", (pid,))
        self.conn.commit()
        return pid

    def get_posting(self, posting_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM postings WHERE id = ?", (posting_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"posting {posting_id}")
        return dict(row)

    def list_postings(self, stage: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = ("SELECT p.id, p.title, p.company, p.location, p.url, p.stage, p.notes, "
               "p.created_at, p.updated_at, a.score FROM postings p "
               "LEFT JOIN analyses a ON a.posting_id = p.id AND a.resume_id = "
               "(SELECT id FROM resumes WHERE is_active = 1 ORDER BY id DESC LIMIT 1) ")
        args: list[Any] = []
        if stage:
            sql += "WHERE p.stage = ? "
            args.append(stage)
        sql += "ORDER BY p.updated_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def set_stage(self, posting_id: int, stage: str, notes: str | None = None) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; choose from {list(STAGES)}")
        current = self.get_posting(posting_id)
        if notes is None:
            self.conn.execute("UPDATE postings SET stage = ?, updated_at = ? WHERE id = ?",
                              (stage, _now(), posting_id))
        else:
            self.conn.execute(
                "UPDATE postings SET stage = ?, notes = ?, updated_at = ? WHERE id = ?",
                (stage, notes, _now(), posting_id))
        if current["stage"] != stage:
            self.conn.execute(
                "INSERT INTO stage_events (posting_id, from_stage, to_stage) VALUES (?, ?, ?)",
                (posting_id, current["stage"], stage))
        self.conn.commit()
        return self.get_posting(posting_id)

    def delete_posting(self, posting_id: int) -> None:
        self.conn.execute("DELETE FROM postings WHERE id = ?", (posting_id,))
        self.conn.commit()

    # ---------------- analyses ----------------
    def save_analysis(self, posting_id: int, resume_id: int, result: MatchResult) -> None:
        self.conn.execute(
            "INSERT INTO analyses (posting_id, resume_id, score, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (posting_id, resume_id) DO UPDATE SET "
            "score = excluded.score, result_json = excluded.result_json, "
            "created_at = excluded.created_at",
            (posting_id, resume_id, result.score, json.dumps(result.to_dict()), _now()))
        self.conn.commit()

    def get_analysis(self, posting_id: int, resume_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT score, result_json, created_at FROM analyses "
            "WHERE posting_id = ? AND resume_id = ?", (posting_id, resume_id)).fetchone()
        if row is None:
            return None
        return {"score": row["score"], "created_at": row["created_at"],
                **json.loads(row["result_json"])}

    def analyze(self, posting_id: int, resume_id: int | None = None,
                refresh: bool = False) -> dict[str, Any]:
        """Score one posting against a resume, using the cache unless `refresh`."""
        resume_row = self.get_resume(resume_id) if resume_id else self.active_resume()
        if resume_row is None:
            raise NotFoundError("no active resume; add one first")
        rid = int(resume_row["id"])
        if not refresh:
            cached = self.get_analysis(posting_id, rid)
            if cached:
                return {**cached, "cached": True, "resume_id": rid}
        posting = self.get_posting(posting_id)
        spec = parse_job_description(posting["text"], posting["title"], posting["company"])
        result = match(parse_resume(resume_row["text"], resume_row["label"]), spec)
        self.save_analysis(posting_id, rid, result)
        return {**result.to_dict(), "cached": False, "resume_id": rid,
                "created_at": _now(), "score": result.score}

    def specs_and_resume(self, resume_id: int | None = None,
                         stages: tuple[str, ...] = ACTIVE_STAGES) -> tuple[Resume, list[JobSpec]]:
        """The active resume and every saved posting, parsed — input for gap analysis."""
        resume_row = self.get_resume(resume_id) if resume_id else self.active_resume()
        if resume_row is None:
            raise NotFoundError("no active resume; add one first")
        unknown = set(stages) - set(STAGES)
        if unknown:
            raise ValueError(f"unknown stages: {sorted(unknown)}")
        # Only the number of placeholders is interpolated; the values stay bound.
        placeholders = ",".join("?" * len(stages))
        rows = self.conn.execute(
            f"SELECT * FROM postings WHERE stage IN ({placeholders})",  # noqa: S608
            stages).fetchall()
        specs = [parse_job_description(r["text"], r["title"], r["company"]) for r in rows]
        return parse_resume(resume_row["text"], resume_row["label"]), specs

    # ---------------- funnel ----------------
    def funnel(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT stage, COUNT(*) AS n FROM postings GROUP BY stage").fetchall()
        counts = {s: 0 for s in STAGES}
        counts.update({r["stage"]: r["n"] for r in rows})
        return counts
