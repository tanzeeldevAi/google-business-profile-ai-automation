"""SQLite state.

Three jobs:
  1. Never reply to the same review twice, never post the same post twice.
  2. Keep an audit history so you can show a client the before and after.
  3. Keep profile snapshots so watch.py can tell you what changed, and who
     changed it -- a hijacked listing shows up here first.

Everything is keyed by location so one install can hold many clients.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Iterable

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    location     TEXT NOT NULL,
    kind         TEXT NOT NULL,      -- review_reply | post | fix | photo | answer
    target       TEXT NOT NULL,      -- review name, post id, field path
    detail       TEXT,
    dry_run      INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS actions_unique
    ON actions(location, kind, target) WHERE dry_run = 0;

CREATE TABLE IF NOT EXISTS audits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    location     TEXT NOT NULL,
    title        TEXT,
    score        INTEGER NOT NULL,
    grade        TEXT,
    findings     TEXT NOT NULL,      -- json
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    location     TEXT NOT NULL,
    payload      TEXT NOT NULL,      -- json of the fields we watch
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    location     TEXT NOT NULL,
    severity     TEXT NOT NULL,
    message      TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);
"""


def conn() -> sqlite3.Connection:
    config.ensure_dirs()
    cx = sqlite3.connect(config.DB_PATH)
    cx.row_factory = sqlite3.Row
    return cx


def init() -> None:
    with conn() as cx:
        cx.executescript(SCHEMA)


# ----------------------------------------------------------------- idempotence

def already_done(location: str, kind: str, target: str) -> bool:
    with conn() as cx:
        row = cx.execute(
            "SELECT 1 FROM actions WHERE location=? AND kind=? AND target=? "
            "AND dry_run=0", (location, kind, target)).fetchone()
        return row is not None


def record_action(location: str, kind: str, target: str, detail: str = "",
                  dry_run: bool = False) -> None:
    with conn() as cx:
        cx.execute(
            "INSERT OR IGNORE INTO actions "
            "(location, kind, target, detail, dry_run, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (location, kind, target, detail[:2000], 1 if dry_run else 0, time.time()))


def recent_actions(location: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
    sql = "SELECT * FROM actions"
    args: list[Any] = []
    if location:
        sql += " WHERE location=?"
        args.append(location)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with conn() as cx:
        return cx.execute(sql, args).fetchall()


def count_since(location: str, kind: str, seconds: float) -> int:
    with conn() as cx:
        row = cx.execute(
            "SELECT COUNT(*) AS n FROM actions WHERE location=? AND kind=? "
            "AND dry_run=0 AND created_at > ?",
            (location, kind, time.time() - seconds)).fetchone()
        return row["n"]


# ---------------------------------------------------------------- audit history

def save_audit(location: str, title: str, score: int, grade: str,
               findings: Iterable[dict]) -> int:
    with conn() as cx:
        cur = cx.execute(
            "INSERT INTO audits (location, title, score, grade, findings, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (location, title, score, grade, json.dumps(list(findings)), time.time()))
        return cur.lastrowid


def audit_history(location: str, limit: int = 12) -> list[sqlite3.Row]:
    with conn() as cx:
        return cx.execute(
            "SELECT id, score, grade, created_at FROM audits WHERE location=? "
            "ORDER BY created_at DESC LIMIT ?", (location, limit)).fetchall()


def previous_score(location: str) -> int | None:
    """The score before the most recent one, for 'up 14 points since June'."""
    rows = audit_history(location, limit=2)
    return rows[1]["score"] if len(rows) > 1 else None


# -------------------------------------------------------------------- watching

def save_snapshot(location: str, payload: dict) -> None:
    with conn() as cx:
        cx.execute(
            "INSERT INTO snapshots (location, payload, created_at) VALUES (?,?,?)",
            (location, json.dumps(payload, sort_keys=True), time.time()))


def last_snapshot(location: str) -> dict | None:
    with conn() as cx:
        row = cx.execute(
            "SELECT payload FROM snapshots WHERE location=? "
            "ORDER BY created_at DESC LIMIT 1", (location,)).fetchone()
        return json.loads(row["payload"]) if row else None


def add_alert(location: str, severity: str, message: str) -> None:
    with conn() as cx:
        cx.execute(
            "INSERT INTO alerts (location, severity, message, created_at) "
            "VALUES (?,?,?,?)", (location, severity, message, time.time()))


def open_alerts(location: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM alerts WHERE acknowledged=0"
    args: list[Any] = []
    if location:
        sql += " AND location=?"
        args.append(location)
    sql += " ORDER BY created_at DESC"
    with conn() as cx:
        return cx.execute(sql, args).fetchall()


def acknowledge_alerts(location: str | None = None) -> int:
    sql = "UPDATE alerts SET acknowledged=1 WHERE acknowledged=0"
    args: list[Any] = []
    if location:
        sql += " AND location=?"
        args.append(location)
    with conn() as cx:
        return cx.execute(sql, args).rowcount
