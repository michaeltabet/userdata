"""SQLite invariants from SDD section 7 hold as database constraints."""

import sqlite3

import pytest

from userdata import ids
from userdata.engines import oltp


def _insert_event(
    store: oltp.OltpEngine, stream: str = "preference:global", seq: int = 1
) -> str:
    """Inserts one event and returns its id.

    Args:
        store: A migrated OLTP engine.
        stream: The event stream.
        seq: The position in the stream.

    Returns:
        The new event_id.
    """
    event_id = ids.new_id()
    store.execute(
        "insert into event (event_id, stream, stream_seq, type, payload,"
        " payload_schema, actor_id, recorded_at)"
        " values (?, ?, ?, 'preference_set', '{}', 'preference_set@1',"
        " 'claude', ?)",
        (event_id, stream, seq, ids.now_iso()),
    )
    return event_id


def _insert_assignment(
    store: oltp.OltpEngine,
    target_id: str,
    valid_from: str,
    valid_to: str,
    exchange: str | None = "XNAS",
) -> str:
    """Assigns ticker ABC to a listing for [valid_from, valid_to).

    Args:
        store: A migrated OLTP engine.
        target_id: The listing id.
        valid_from: First day, inclusive.
        valid_to: Last day, exclusive.
        exchange: The exchange MIC the ticker is on.

    Returns:
        The new assignment_id.
    """
    assignment_id = ids.new_id()
    store.execute(
        "insert into identifier_assignment (assignment_id, scheme, value,"
        " level, target_id, exchange, valid_from, valid_to, recorded_at)"
        " values (?, 'ticker', 'ABC', 'listing', ?, ?, ?, ?, ?)",
        (
            assignment_id,
            target_id,
            exchange,
            valid_from,
            valid_to,
            ids.now_iso(),
        ),
    )
    return assignment_id


def _insert_claim(store: oltp.OltpEngine) -> str:
    """Inserts a thesis with one claim and returns the claim id.

    Args:
        store: A migrated OLTP engine.

    Returns:
        The new claim_id.
    """
    thesis_id, claim_id = ids.new_id(), ids.new_id()
    store.execute(
        "insert into thesis (thesis_id, stance, opened_on, actor_id)"
        " values (?, 'long', '2026-10-30', 'michael')",
        (thesis_id,),
    )
    store.execute(
        "insert into thesis_claim (claim_id, thesis_id, kind, statement,"
        " kill_criterion, opened_on)"
        " values (?, ?, 'valuation', 'cheap', 'not cheap', '2026-10-30')",
        (claim_id, thesis_id),
    )
    return claim_id


def _insert_evidence(
    store: oltp.OltpEngine,
    claim_id: str,
    chunk_id: str | None,
    fact_row_id: str | None,
) -> None:
    """Links a claim to the given sources.

    Args:
        store: A migrated OLTP engine.
        claim_id: The claim the evidence supports.
        chunk_id: A DuckDB chunk id, or None.
        fact_row_id: A DuckDB fact id, or None.
    """
    store.execute(
        "insert into evidence (evidence_id, claim_id, role, chunk_id,"
        " fact_row_id, created_by, created_at)"
        " values (?, ?, 'supports', ?, ?, 'claude', ?)",
        (ids.new_id(), claim_id, chunk_id, fact_row_id, ids.now_iso()),
    )


def test_event_update_raises(store: oltp.OltpEngine) -> None:
    """An event cannot be edited."""
    event_id = _insert_event(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.execute(
            "update event set type = 'other' where event_id = ?", (event_id,)
        )


def test_event_delete_raises(store: oltp.OltpEngine) -> None:
    """An event cannot be deleted."""
    event_id = _insert_event(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.execute("delete from event where event_id = ?", (event_id,))


def test_event_stream_seq_is_unique(store: oltp.OltpEngine) -> None:
    """Two events cannot share (stream, stream_seq)."""
    _insert_event(store, "session:1", 1)
    _insert_event(store, "session:1", 2)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _insert_event(store, "session:1", 2)


def test_bad_timestamp_raises(store: oltp.OltpEngine) -> None:
    """A timestamp not in YYYY-MM-DDTHH:MM:SSZ form is rejected."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.execute(
            "insert into event (event_id, stream, stream_seq, type, payload,"
            " payload_schema, actor_id, recorded_at)"
            " values ('e', 's', 1, 't', '{}', 't@1', 'claude',"
            " '2026-10-30 12:00:00')"
        )


def test_identifier_overlap_raises(store: oltp.OltpEngine) -> None:
    """A ticker cannot point at two listings on the same day."""
    _insert_assignment(store, "listing-a", "2024-01-01", "9999-12-31")
    with pytest.raises(sqlite3.IntegrityError, match="overlaps"):
        _insert_assignment(store, "listing-b", "2025-06-01", "9999-12-31")


def test_identifier_adjacent_succeeds(store: oltp.OltpEngine) -> None:
    """Back-to-back half-open intervals do not overlap."""
    _insert_assignment(store, "listing-a", "2024-01-01", "2025-01-01")
    _insert_assignment(store, "listing-b", "2025-01-01", "9999-12-31")
    rows = store.execute("select count(*) from identifier_assignment")
    assert rows == [(2,)]


def test_identifier_update_into_overlap_raises(
    store: oltp.OltpEngine,
) -> None:
    """Moving an interval onto another one is rejected too."""
    _insert_assignment(store, "listing-a", "2024-01-01", "2025-01-01")
    second = _insert_assignment(store, "listing-b", "2025-01-01", "9999-12-31")
    with pytest.raises(sqlite3.IntegrityError, match="overlaps"):
        store.execute(
            "update identifier_assignment set valid_from = '2024-12-01'"
            " where assignment_id = ?",
            (second,),
        )


def test_ticker_on_two_exchanges_succeeds(store: oltp.OltpEngine) -> None:
    """One ticker may name different listings on different exchanges."""
    _insert_assignment(store, "listing-a", "2024-01-01", "9999-12-31")
    _insert_assignment(
        store, "listing-b", "2024-01-01", "9999-12-31", exchange="XLON"
    )
    rows = store.execute("select count(*) from identifier_assignment")
    assert rows == [(2,)]


def test_ticker_without_exchange_raises(store: oltp.OltpEngine) -> None:
    """A ticker assignment must say which exchange it is on."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_assignment(
            store, "listing-a", "2024-01-01", "9999-12-31", exchange=None
        )


def test_non_ticker_overlap_raises(store: oltp.OltpEngine) -> None:
    """Null exchanges compare equal, so a CIK still has one target."""
    sql = (
        "insert into identifier_assignment (assignment_id, scheme, value,"
        " level, target_id, valid_from, recorded_at)"
        " values (?, 'cik', '0000000001', 'issuer', ?, '2024-01-01', ?)"
    )
    store.execute(sql, (ids.new_id(), "issuer-a", ids.now_iso()))
    with pytest.raises(sqlite3.IntegrityError, match="overlaps"):
        store.execute(sql, (ids.new_id(), "issuer-b", ids.now_iso()))


def _insert_issuer(store: oltp.OltpEngine, issuer_id: str) -> None:
    """Inserts a minimal issuer.

    Args:
        store: A migrated OLTP engine.
        issuer_id: The id to use.
    """
    store.execute(
        "insert into issuer (issuer_id, name, business_address_schema,"
        " mailing_address_schema, recorded_at)"
        " values (?, 'Example Corp', 'address@1', 'address@1', ?)",
        (issuer_id, ids.now_iso()),
    )


def test_peer_group_member_can_be_re_added(store: oltp.OltpEngine) -> None:
    """A dropped peer can join again; both memberships are kept."""
    _insert_issuer(store, "cik:0000000001")
    group_id = ids.new_id()
    store.execute(
        "insert into peer_group (peer_group_id, name, basis, actor_id,"
        " created_at) values (?, 'peers', 'manual', 'michael', ?)",
        (group_id, ids.now_iso()),
    )
    member = (
        "insert into peer_group_member (peer_group_id, issuer_id, added_at,"
        " removed_at) values (?, 'cik:0000000001', ?, ?)"
    )
    store.execute(
        member, (group_id, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    )
    store.execute(member, (group_id, "2026-03-01T00:00:00Z", None))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.execute(member, (group_id, "2026-03-01T00:00:00Z", None))
    rows = store.execute("select count(*) from peer_group_member")
    assert rows == [(2,)]


def _seed_insert_only_rows(store: oltp.OltpEngine) -> None:
    """Writes one row to each of screen_version, company_note, relation.

    Args:
        store: A migrated OLTP engine.
    """
    now = ids.now_iso()
    _insert_issuer(store, "cik:0000000001")
    store.execute(
        "insert into screen (screen_id, name) values ('sc-1', 'value')"
    )
    store.execute(
        "insert into screen_version (screen_version_id, screen_id, version,"
        " rules, rules_schema, created_by, created_at)"
        " values ('sv-1', 'sc-1', 1, '{}', 'rules@1', 'michael', ?)",
        (now,),
    )
    store.execute(
        "insert into company_note (note_id, issuer_id, body, actor_id,"
        " created_at) values ('cn-1', 'cik:0000000001', 'note', 'michael', ?)",
        (now,),
    )
    version_id = _insert_taxonomy_version(store, "draft")
    store.execute(
        "insert into concept (concept_id, taxonomy_id, local_name) values"
        " ('mt:A', 'mt', 'A'), ('mt:B', 'mt', 'B')"
    )
    store.execute(
        "insert into concept_relation (taxonomy_version_id, from_concept_id,"
        " to_concept_id, arcrole) values (?, 'mt:A', 'mt:B', 'parent-child')",
        (version_id,),
    )


@pytest.mark.parametrize(
    "statement",
    [
        "update screen_version set rules = '[]'",
        "delete from screen_version",
        "update company_note set body = 'edited'",
        "delete from company_note",
        "update concept_relation set weight = 2",
        "delete from concept_relation",
    ],
)
def test_insert_only_tables_raise(
    store: oltp.OltpEngine, statement: str
) -> None:
    """screen_version, company_note and concept_relation are insert-only."""
    _seed_insert_only_rows(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.execute(statement)


def test_evidence_with_one_source_succeeds(store: oltp.OltpEngine) -> None:
    """Exactly one source is the valid case."""
    claim_id = _insert_claim(store)
    _insert_evidence(store, claim_id, None, ids.row_id("fact"))
    assert store.execute("select count(*) from evidence") == [(1,)]


def test_evidence_with_two_sources_raises(store: oltp.OltpEngine) -> None:
    """Evidence cannot point at two sources."""
    claim_id = _insert_claim(store)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_evidence(
            store, claim_id, ids.row_id("chunk"), ids.row_id("fact")
        )


def test_evidence_with_no_source_raises(store: oltp.OltpEngine) -> None:
    """Evidence must point at some source."""
    claim_id = _insert_claim(store)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _insert_evidence(store, claim_id, None, None)


def _insert_taxonomy_version(store: oltp.OltpEngine, status: str) -> str:
    """Inserts a version of the mt taxonomy and returns its id.

    Args:
        store: A migrated OLTP engine.
        status: draft, validated or published.

    Returns:
        The new taxonomy_version_id.
    """
    version_id = ids.new_id()
    now = ids.now_iso()
    (next_version,) = store.execute(
        "select coalesce(max(version), 0) + 1 from taxonomy_version"
    )[0]
    store.execute(
        "insert into taxonomy_version (taxonomy_version_id, taxonomy_id,"
        " version, status, created_by, created_at, published_at)"
        " values (?, 'mt', ?, ?, 'michael', ?, ?)",
        (
            version_id,
            next_version,
            status,
            now,
            now if status == "published" else None,
        ),
    )
    return version_id


def _insert_concept_version(store: oltp.OltpEngine, version_id: str) -> None:
    """Adds mt:AdjustedEbitda to a taxonomy version.

    Args:
        store: A migrated OLTP engine.
        version_id: The taxonomy version to add it to.
    """
    store.execute(
        "insert or ignore into concept (concept_id, taxonomy_id, local_name)"
        " values ('mt:AdjustedEbitda', 'mt', 'AdjustedEbitda')"
    )
    store.execute(
        "insert into concept_version (concept_version_id, concept_id,"
        " taxonomy_version_id, data_type, period_type, balance,"
        " labels_schema)"
        " values (?, 'mt:AdjustedEbitda', ?, 'monetaryItemType',"
        " 'duration', 'credit', 'labels@1')",
        (ids.new_id(), version_id),
    )


def test_concept_version_into_draft_succeeds(store: oltp.OltpEngine) -> None:
    """A draft taxonomy version accepts new concept versions."""
    _insert_concept_version(store, _insert_taxonomy_version(store, "draft"))
    assert store.execute("select count(*) from concept_version") == [(1,)]


def test_concept_version_into_published_raises(
    store: oltp.OltpEngine,
) -> None:
    """A published taxonomy version is frozen."""
    published = _insert_taxonomy_version(store, "published")
    with pytest.raises(sqlite3.IntegrityError, match="published"):
        _insert_concept_version(store, published)


def test_concept_mapping_into_published_raises(
    store: oltp.OltpEngine,
) -> None:
    """Mappings cannot be added to a published taxonomy version."""
    draft = _insert_taxonomy_version(store, "draft")
    _insert_concept_version(store, draft)
    published = _insert_taxonomy_version(store, "published")
    with pytest.raises(sqlite3.IntegrityError, match="published"):
        store.execute(
            "insert into concept_mapping (mapping_id, taxonomy_version_id,"
            " target_concept_id, input_concept_id)"
            " values (?, ?, 'mt:AdjustedEbitda', 'mt:AdjustedEbitda')",
            (ids.new_id(), published),
        )
