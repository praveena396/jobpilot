"""Database layer — SQLite for application tracking."""

import sqlite3
from datetime import datetime
from pathlib import Path

from jobpilot import get, get_root

_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    linkedin_url TEXT,
    full_name TEXT,
    headline TEXT,
    summary TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    level TEXT,
    location TEXT,
    comp_min INTEGER,
    comp_max INTEGER,
    url TEXT UNIQUE NOT NULL,
    description TEXT,
    match_score INTEGER DEFAULT 0,
    posted_at TEXT,
    discovered_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    resume_version TEXT,
    cover_letter_path TEXT,
    applied_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'applied',
    follow_up_date TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS work_history (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id),
    company TEXT,
    title TEXT,
    start_date TEXT,
    end_date TEXT,
    bullets TEXT,
    order_idx INTEGER
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id),
    name TEXT,
    category TEXT,
    endorsements INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS education (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id),
    institution TEXT,
    degree TEXT,
    field TEXT,
    start_year INTEGER,
    end_year INTEGER
);
"""


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    db_path = Path(get("database.path", "data/jobpilot.db"))
    if not db_path.is_absolute():
        db_path = get_root() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path))
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
    return _conn


def insert_job(job: dict) -> int | None:
    db = get_db()
    try:
        cur = db.execute(
            """INSERT OR IGNORE INTO jobs (source, company, title, level, location,
               comp_min, comp_max, url, description, match_score, posted_at)
               VALUES (:source, :company, :title, :level, :location,
               :comp_min, :comp_max, :url, :description, :match_score, :posted_at)""",
            job,
        )
        db.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    except sqlite3.Error:
        return None


def insert_application(app: dict) -> int:
    db = get_db()
    cur = db.execute(
        """INSERT INTO applications (job_id, resume_version, cover_letter_path, status, follow_up_date, notes)
           VALUES (:job_id, :resume_version, :cover_letter_path, :status, :follow_up_date, :notes)""",
        app,
    )
    db.commit()
    return cur.lastrowid


def update_application_status(app_id: int, status: str, notes: str = ""):
    db = get_db()
    db.execute(
        "UPDATE applications SET status = ?, notes = notes || ? WHERE id = ?",
        (status, f"\n{notes}" if notes else "", app_id),
    )
    db.commit()


def get_applications(status: str | None = None) -> list[dict]:
    db = get_db()
    if status:
        rows = db.execute(
            """SELECT a.*, j.company, j.title, j.url, j.comp_min, j.comp_max
               FROM applications a JOIN jobs j ON a.job_id = j.id
               WHERE a.status = ? ORDER BY a.applied_at DESC""",
            (status,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT a.*, j.company, j.title, j.url, j.comp_min, j.comp_max
               FROM applications a JOIN jobs j ON a.job_id = j.id
               ORDER BY a.applied_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_todays_application_count() -> int:
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM applications WHERE date(applied_at) = date('now')"
    ).fetchone()
    return row["cnt"]


def get_pending_followups() -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT a.*, j.company, j.title, j.url
           FROM applications a JOIN jobs j ON a.job_id = j.id
           WHERE a.status = 'applied' AND a.follow_up_date <= date('now')
           ORDER BY a.follow_up_date"""
    ).fetchall()
    return [dict(r) for r in rows]
