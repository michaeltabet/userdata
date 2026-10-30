# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Tools for projects, sessions, history and preferences."""

from typing import Any

from mcp.server.mcpserver import Context

from userdata import account
from userdata import stores


async def start_project(
    context: Context, project_name: str, goal_text: str
) -> account.Row:
    """Starts a project that sessions, lists and notes can belong to."""
    row = {
        "project_id": account.new_id(),
        "project_name": project_name,
        "goal_text": goal_text,
        "created_at": account.now(),
    }
    return account.save(
        stores.of(context).account, "projects", row, "project_started"
    )


async def start_session(
    context: Context, session_title: str, project_id: str | None = None
) -> account.Row:
    """Opens a working session; pass its session_id to log."""
    row = {
        "session_id": account.new_id(),
        "project_id": project_id,
        "session_title": session_title,
        "started_at": account.now(),
    }
    return account.save(
        stores.of(context).account, "sessions", row, "session_started"
    )


async def log(
    context: Context, session_id: str, event_type: str, details: account.Row
) -> account.Row:
    """Records what happened, e.g. event_type "decision" or "finding"."""
    return account.record(
        stores.of(context).account, event_type, details, session_id
    )


async def history(
    context: Context,
    session_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
) -> list[account.Row]:
    """Returns what was done, newest first, for a session or project."""
    return account.history(
        stores.of(context).account, session_id, project_id, limit
    )


async def set_preference(
    context: Context, preference_key: str, preference_value: Any
) -> account.Row:
    """Remembers how Michael wants things done."""
    row = {
        "preference_key": preference_key,
        "preference_value": preference_value,
        "updated_at": account.now(),
    }
    return account.save(
        stores.of(context).account,
        "preferences",
        row,
        "preference_set",
        "michael",
        replace=True,
    )


TOOLS = [
    start_project,
    start_session,
    log,
    history,
    set_preference,
]
