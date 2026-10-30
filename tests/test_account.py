# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The account keeps history: nothing written is lost or silently changed."""

import json
import sqlite3

import pytest

from userdata import account


def _note(store, text):
    row = {
        "note_id": account.new_id(),
        "ticker": "AEP",
        "note_text": text,
        "created_at": account.now(),
    }
    return account.save(store, "notes", row, "note_added")


def test_every_write_lands_in_history(stores):
    store, _ = stores
    _note(store, "first")
    _note(store, "second")

    events = account.history(store)

    assert [
        json.loads(event["event_details"])["note_text"] for event in events
    ] == [
        "second",
        "first",
    ]


def test_events_cannot_be_edited(stores):
    store, _ = stores
    _note(store, "x")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.execute("update events set event_type = 'x'")


def test_a_failed_write_records_nothing(stores):
    store, _ = stores
    with pytest.raises(sqlite3.IntegrityError):
        account.save(store, "notes", {"note_id": "1"}, "note_added")

    assert account.history(store) == []


def test_list_keeps_who_was_dropped_and_readded(stores):
    store, _ = stores
    account.save(
        store,
        "lists",
        {"list_name": "peers", "list_type": "peer_group", "created_at": "t"},
        "list_created",
    )
    for reason in ("same regulator", "back in"):
        member = {
            "list_name": "peers",
            "ticker": "AEP",
            "reason_text": reason,
            "added_at": account.now(),
        }
        account.save(store, "list_members", member, "list_added")
        if reason == "same regulator":
            account.remove_from_list(store, "peers", "AEP")

    everyone = account.select(store, "select * from list_members")
    current = [row for row in everyone if row["removed_at"] is None]

    assert len(everyone) == 2
    assert [row["reason_text"] for row in current] == ["back in"]


def test_a_ticker_is_on_a_list_once_at_a_time(stores):
    store, _ = stores
    account.save(
        store,
        "lists",
        {"list_name": "w", "list_type": "watchlist", "created_at": "t"},
        "list_created",
    )
    member = {"list_name": "w", "ticker": "AEP", "added_at": account.now()}
    account.save(store, "list_members", member, "list_added")

    with pytest.raises(sqlite3.IntegrityError):
        account.save(
            store, "list_members", member | {"added_at": "later"}, "list_added"
        )


def test_versions_count_up(stores):
    store, _ = stores
    formula = [{"concept": "us-gaap:OperatingIncomeLoss", "weight": 1}]
    for text in ("first", "second"):
        row = {
            "concept_name": "mt:Ebit",
            "definition_text": text,
            "concept_formula": formula,
            "version_number": account.next_version(
                store, "concepts", "mt:Ebit"
            ),
            "created_at": account.now(),
        }
        account.save(store, "concepts", row, "concept_defined")

    concept = account.latest_concept(store, "mt:Ebit")

    assert concept["version_number"] == 2
    assert concept["concept_formula"] == formula
