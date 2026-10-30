"""Deterministic ids, canonical dimension keys and timestamps."""

import sqlite3

import pytest

from userdata import ids

# The same pattern the schema's timestamp checks use.
_TIMESTAMP_GLOB = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
    "T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z"
)


def test_row_id_is_deterministic() -> None:
    """The same parts always give the same 64-character hex id."""
    first = ids.row_id("0000320193-25-000001", "us-gaap:Revenues", None)
    second = ids.row_id("0000320193-25-000001", "us-gaap:Revenues", None)
    assert first == second
    assert len(first) == 64
    assert int(first, 16) >= 0


def test_row_id_is_order_sensitive() -> None:
    """Swapping two parts changes the id."""
    assert ids.row_id("a", "b") != ids.row_id("b", "a")


def test_row_id_parts_do_not_run_together() -> None:
    """('ab', 'c') and ('a', 'bc') hash differently."""
    assert ids.row_id("ab", "c") != ids.row_id("a", "bc")


def test_row_id_none_hashes_as_empty() -> None:
    """A null key column hashes like the empty string."""
    assert ids.row_id("a", None) == ids.row_id("a", "")


def test_row_id_rejects_separator() -> None:
    """A part containing the separator would be ambiguous."""
    with pytest.raises(ValueError, match="separator"):
        ids.row_id("a\x1fb")


def test_dimensions_key_sorts_by_axis() -> None:
    """Axes come out sorted whatever the input order."""
    dims = {
        "us-gaap:StatementBusinessSegmentsAxis": "abc:RetailMember",
        "srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember",
    }
    assert ids.dimensions_key(dims) == (
        "srt:ConsolidationItemsAxis=us-gaap:OperatingSegmentsMember;"
        "us-gaap:StatementBusinessSegmentsAxis=abc:RetailMember"
    )


def test_dimensions_key_canonicalises_whitespace() -> None:
    """Surrounding whitespace does not change the key."""
    assert ids.dimensions_key({" b:Axis ": "b:M ", "a:Axis": " a:M"}) == (
        "a:Axis=a:M;b:Axis=b:M"
    )


def test_dimensions_key_empty() -> None:
    """No dimensions is the empty string."""
    assert ids.dimensions_key(None) == ""
    assert ids.dimensions_key({}) == ""


@pytest.mark.parametrize(
    "dims",
    [{"a=b": "m"}, {"a": "m;n"}, {"a": " "}, {"a": "m", " a ": "n"}],
)
def test_dimensions_key_rejects_bad_parts(dims: dict[str, str]) -> None:
    """Separators, empty parts and duplicate axes are rejected."""
    with pytest.raises(ValueError):
        ids.dimensions_key(dims)


def test_new_id_is_uuid7() -> None:
    """new_id gives version-7 UUIDs that sort by creation time."""
    first, second = ids.new_id(), ids.new_id()
    assert len(first) == 36
    assert first[14] == "7"
    assert first < second


def test_now_iso_matches_schema_glob() -> None:
    """now_iso passes the same glob the SQLite checks apply."""
    conn = sqlite3.connect(":memory:")
    try:
        (matched,) = conn.execute(
            "select ? glob ?", (ids.now_iso(), _TIMESTAMP_GLOB)
        ).fetchone()
    finally:
        conn.close()
    assert matched == 1
