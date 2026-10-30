# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Tools for watchlists, peer groups, notes and tags."""

import sqlite3

from mcp.server import mcpserver

from userdata import account
from userdata import stores


async def create_list(
    context: mcpserver.Context,
    list_name: str,
    list_type: str,
    purpose_text: str,
    project_id: str | None = None,
) -> account.Row:
    """Creates a list; list_type is "watchlist" or "peer_group"."""
    row = {
        "list_name": list_name,
        "project_id": project_id,
        "list_type": list_type,
        "purpose_text": purpose_text,
        "created_at": account.now(),
    }
    return account.save(
        stores.from_context(context).account, "lists", row, "list_created"
    )


async def add_to_list(
    context: mcpserver.Context, list_name: str, ticker: str, reason_text: str
) -> account.Row:
    """Puts a ticker on a watchlist or peer group."""
    row = {
        "list_name": list_name,
        "ticker": ticker.upper(),
        "reason_text": reason_text,
        "added_at": account.now(),
    }
    return account.save(
        stores.from_context(context).account, "list_members", row, "list_added"
    )


async def remove_from_list(
    context: mcpserver.Context, list_name: str, ticker: str
) -> account.Row:
    """Takes a ticker off a list; the history keeps that it was there."""
    return _mark_removed(
        stores.from_context(context).account, list_name, ticker
    )


async def add_note(
    context: mcpserver.Context,
    note_text: str,
    ticker: str,
    project_id: str | None = None,
) -> account.Row:
    """Writes a note; ticker may be empty."""
    row = {
        "note_id": account.new_id(),
        "project_id": project_id,
        "ticker": ticker.upper(),
        "note_text": note_text,
        "created_at": account.now(),
    }
    return account.save(
        stores.from_context(context).account, "notes", row, "note_added"
    )


async def tag(
    context: mcpserver.Context,
    tag_name: str,
    target_type: str,
    target_id: str,
    note_text: str,
) -> account.Row:
    """Tags a "filing" (accession), "fact" (fact_id), "ticker" or "note"."""
    row = {
        "tag_name": tag_name,
        "target_type": target_type,
        "target_id": target_id,
        "note_text": note_text,
        "tagged_at": account.now(),
    }
    return account.save(
        stores.from_context(context).account,
        "taggings",
        row,
        "tagged",
        "michael",
        replace=True,
    )


def _mark_removed(
    account_store: sqlite3.Connection, list_name: str, ticker: str
) -> account.Row:
    removed = {"list_name": list_name, "ticker": ticker.upper()}
    with stores.transaction(account_store):
        account_store.execute(
            "update list_members set removed_at = ? where list_name = ?"
            " and ticker = ? and removed_at is null",
            (account.now(), list_name, removed["ticker"]),
        )
        account.record(account_store, "list_removed", removed)
    return removed


TOOLS = (
    create_list,
    add_to_list,
    remove_from_list,
    add_note,
    tag,
)
