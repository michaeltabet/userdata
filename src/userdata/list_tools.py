# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Tools for watchlists, peer groups, notes and tags."""

from mcp.server.mcpserver import Context

from userdata import account
from userdata import stores


async def create_list(
    context: Context,
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
        stores.of(context).account, "lists", row, "list_created"
    )


async def add_to_list(
    context: Context, list_name: str, ticker: str, reason_text: str
) -> account.Row:
    """Puts a ticker on a watchlist or peer group."""
    row = {
        "list_name": list_name,
        "ticker": ticker.upper(),
        "reason_text": reason_text,
        "added_at": account.now(),
    }
    return account.save(
        stores.of(context).account, "list_members", row, "list_added"
    )


async def remove_from_list(
    context: Context, list_name: str, ticker: str
) -> account.Row:
    """Takes a ticker off a list; the history keeps that it was there."""
    return account.remove_from_list(
        stores.of(context).account, list_name, ticker
    )


async def add_note(
    context: Context,
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
    return account.save(stores.of(context).account, "notes", row, "note_added")


async def tag(
    context: Context,
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
        stores.of(context).account,
        "taggings",
        row,
        "tagged",
        "michael",
        replace=True,
    )


TOOLS = [
    create_list,
    add_to_list,
    remove_from_list,
    add_note,
    tag,
]
