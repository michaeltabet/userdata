# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Tools that pull EDGAR and Yahoo data and query both stores."""

import contextlib
import sqlite3
from typing import Any

from mcp.server.mcpserver import Context

from userdata import account
from userdata import market
from userdata import sec
from userdata import stores
from userdata import yahoo


async def pull_company(context: Context, ticker: str) -> account.Row:
    """Stores a company's SEC profile and returns it, CIK included."""
    opened = stores.of(context)
    company = sec.pull_company(opened.market, ticker)
    _record_pull(opened, ticker, "company")
    return company


async def pull_filings(
    context: Context, ticker: str, form_type: str, limit: int
) -> account.Row:
    """Stores the latest filings of one form type, e.g. "10-K" or "8-K"."""
    opened = stores.of(context)
    count = sec.pull_filings(opened.market, ticker, form_type, limit)
    return _record_pull(opened, ticker, "filings", count=count)


async def pull_facts(context: Context, ticker: str) -> account.Row:
    """Stores every XBRL fact SEC holds for a company."""
    opened = stores.of(context)
    count = sec.pull_facts(opened.market, ticker)
    return _record_pull(opened, ticker, "facts", count=count)


async def pull_prices(
    context: Context, ticker: str, period: str
) -> account.Row:
    """Stores daily prices for a Yahoo period such as "1y" or "max"."""
    opened = stores.of(context)
    count = yahoo.pull_prices(opened.market, ticker, period)
    return _record_pull(opened, ticker, "prices", count=count)


async def pull_statements(
    context: Context, ticker: str, timescale: str
) -> account.Row:
    """Stores Yahoo's statements; timescale is yearly, quarterly or trailing."""
    opened = stores.of(context)
    count = yahoo.pull_statements(opened.market, ticker, timescale)
    return _record_pull(opened, ticker, "statements", count=count)


async def pull_profile(context: Context, ticker: str) -> account.Row:
    """Stores Yahoo's profile of a company and returns it."""
    opened = stores.of(context)
    profile = yahoo.pull_profile(opened.market, ticker)
    _record_pull(opened, ticker, "profile")
    return profile


async def query_market(context: Context, sql: str) -> list[account.Row]:
    """Runs one SELECT on the market tables."""
    return market.query(stores.of(context).market, sql)


async def query_account(context: Context, sql: str) -> list[account.Row]:
    """Runs one read-only SELECT on the account tables."""
    uri = f"file:{stores.of(context).config.account_path}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as read_only:
        read_only.row_factory = sqlite3.Row
        return account.select(read_only, sql)


def _record_pull(
    opened: stores.Stores, ticker: str, what: str, **extra: Any
) -> account.Row:
    details = {"ticker": ticker.upper(), "what": what} | extra
    account.record(opened.account, "pulled", details)
    return details


TOOLS = [
    pull_company,
    pull_filings,
    pull_facts,
    pull_prices,
    pull_statements,
    pull_profile,
    query_market,
    query_account,
]
