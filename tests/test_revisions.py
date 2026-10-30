"""A revised payload is a new row; the *_latest views pick the newest."""

from userdata import ids
from userdata.engines import olap


def _insert_price(
    analytics: olap.OlapEngine, raw_sha256: str, close: float, known_at: str
) -> None:
    """Loads one daily price for listing L on 2026-10-29 from a payload.

    Args:
        analytics: A migrated OLAP engine.
        raw_sha256: The payload the price came from.
        close: The closing price.
        known_at: When it was fetched.
    """
    key = ("L", "2026-10-29", "yahoo", raw_sha256)
    analytics.execute(
        "insert into price_daily (price_row_id, listing_id, trade_date,"
        " close, source, known_at, known_at_precision, raw_sha256,"
        " code_version) values (?, ?, ?, ?, ?, ?, 'datetime', ?, 'test@1')"
        " on conflict do nothing",
        (ids.row_id(*key), *key[:2], close, key[2], known_at, raw_sha256),
    )


def test_price_revision_is_a_new_row(analytics: olap.OlapEngine) -> None:
    """Two payloads for one day keep both rows; the newest is latest."""
    _insert_price(analytics, "a" * 64, 10.0, "2026-10-29T21:00:00Z")
    _insert_price(analytics, "b" * 64, 10.5, "2026-10-30T21:00:00Z")
    _insert_price(analytics, "a" * 64, 10.0, "2026-10-29T21:00:00Z")
    assert analytics.execute("select count(*) from price_daily") == [(2,)]
    assert analytics.execute(
        "select close, raw_sha256 from price_latest"
    ) == [(10.5, "b" * 64)]


def test_fx_revision_is_a_new_row(analytics: olap.OlapEngine) -> None:
    """Two payloads for one rate keep both rows; the newest is latest."""
    sql = (
        "insert into fx_rate (base, quote, rate_date, rate, source,"
        " known_at, raw_sha256) values ('GBP', 'USD', '2026-10-29', ?,"
        " 'yahoo', ?, ?) on conflict do nothing"
    )
    analytics.execute(sql, (1.30, "2026-10-29T21:00:00Z", "a" * 64))
    analytics.execute(sql, (1.31, "2026-10-30T21:00:00Z", "b" * 64))
    analytics.execute(sql, (1.30, "2026-10-29T21:00:00Z", "a" * 64))
    assert analytics.execute("select count(*) from fx_rate") == [(2,)]
    assert analytics.execute("select rate from fx_rate_latest") == [(1.31,)]
