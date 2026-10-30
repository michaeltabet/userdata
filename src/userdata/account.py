# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The user's account, kept in the SQLite store."""

import datetime
import json
import sqlite3
import uuid
from typing import Any
from typing import TypeAlias

from userdata import db

Row: TypeAlias = dict[str, Any]


def save(
    account: sqlite3.Connection,
    table: str,
    row: Row,
    event_type: str,
    actor_name: str = "claude",
    replace: bool = False,
) -> Row:
    """Inserts a row and records the change as an event, atomically."""
    stored = {key: _encode(value) for key, value in row.items()}
    verb = "insert or replace" if replace else "insert"
    columns = ", ".join(stored)
    marks = ", ".join("?" * len(stored))
    with db.transaction(account):
        account.execute(
            f"{verb} into {table} ({columns}) values ({marks})",
            tuple(stored.values()),
        )
        record(
            account,
            event_type,
            stored,
            row.get("session_id"),
            row.get("project_id"),
            actor_name,
        )
    return stored


def record(
    account: sqlite3.Connection,
    event_type: str,
    details: Row,
    session_id: str | None = None,
    project_id: str | None = None,
    actor_name: str = "claude",
) -> Row:
    """Appends one event to the history and returns it."""
    event = {
        "event_id": new_id(),
        "session_id": session_id,
        "project_id": project_id,
        "event_type": event_type,
        "actor_name": actor_name,
        "event_details": json.dumps(details, default=str),
        "recorded_at": now(),
    }
    account.execute(
        "insert into events values (?, ?, ?, ?, ?, ?, ?)",
        tuple(event.values()),
    )
    return event


def history(
    account: sqlite3.Connection,
    session_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
) -> list[Row]:
    """Returns events, newest first, for a session, a project or all."""
    return select(
        account,
        "select * from events where (? is null or session_id = ?)"
        " and (? is null or project_id = ?)"
        " order by recorded_at desc, event_id desc limit ?",
        session_id,
        session_id,
        project_id,
        project_id,
        limit,
    )


def remove_from_list(
    account: sqlite3.Connection, list_name: str, ticker: str
) -> Row:
    """Takes a ticker off a list; the membership is kept, marked removed."""
    removed = {"list_name": list_name, "ticker": ticker.upper()}
    with db.transaction(account):
        account.execute(
            "update list_members set removed_at = ? where list_name = ?"
            " and ticker = ? and removed_at is null",
            (now(), list_name, removed["ticker"]),
        )
        record(account, "list_removed", removed)
    return removed


def next_version(account: sqlite3.Connection, table: str, name: str) -> int:
    """Returns the version number a new row of a versioned table gets."""
    key = {"skills": "skill_name", "concepts": "concept_name"}[table]
    row = account.execute(
        f"select coalesce(max(version_number), 0) + 1 from {table}"
        f" where {key} = ?",
        (name,),
    ).fetchone()
    return row[0]


def latest_concept(account: sqlite3.Connection, concept_name: str) -> Row:
    """Returns the newest version of an own concept, formula decoded."""
    rows = select(
        account,
        "select * from concepts where concept_name = ?"
        " order by version_number desc limit 1",
        concept_name,
    )
    if not rows:
        raise KeyError(f"no concept named {concept_name!r}")
    formula = json.loads(rows[0]["concept_formula"])
    return rows[0] | {"concept_formula": formula}


def select(account: sqlite3.Connection, sql: str, *params: Any) -> list[Row]:
    """Runs one query and returns its rows as dicts."""
    return [dict(row) for row in account.execute(sql, params).fetchall()]


def new_id() -> str:
    """Returns a time-ordered id (UUIDv7)."""
    return str(uuid.uuid7())


def now() -> str:
    """Returns the current UTC time, to the microsecond."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def _encode(value: Any) -> Any:
    # pyrefly: ignore[implicit-any-type-argument]
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return value
