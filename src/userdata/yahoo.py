# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Pulls from Yahoo Finance, through yfinance, into the market store."""

import json

import duckdb
import pandas as pd
import yfinance

from userdata import market

_STATEMENTS = {
    "income": "get_income_stmt",
    "balance": "get_balance_sheet",
    "cashflow": "get_cashflow",
}


def pull_prices(
    market_store: duckdb.DuckDBPyConnection, ticker: str, period: str
) -> int:
    """Stores daily prices for a period such as "1y"; returns how many."""
    frame = yfinance.Ticker(ticker).history(period=period, auto_adjust=False)
    frame = market.snake_case(frame.reset_index())
    frame["ticker"] = ticker.upper()
    market.load(
        market_store,
        frame,
        """
        insert or replace into prices
        select
            ticker,
            open as open_price,
            high as high_price,
            low as low_price,
            close as close_price,
            adj_close as adjusted_close_price,
            dividends as dividend_amount,
            stock_splits as split_ratio,
            volume as share_volume,
            cast(date as date) as trade_date,
            current_timestamp as fetched_at
        from frame
        """,
    )
    return len(frame)


def pull_statements(
    market_store: duckdb.DuckDBPyConnection, ticker: str, timescale: str
) -> int:
    """Stores Yahoo's three statements ("yearly", "quarterly", "trailing")."""
    handle = yfinance.Ticker(ticker)
    frames = [
        _statement_rows(getattr(handle, method)(freq=timescale), name)
        for name, method in _STATEMENTS.items()
    ]
    frame = pd.concat(frames, ignore_index=True)
    frame["ticker"] = ticker.upper()
    frame["timescale"] = timescale
    market.load(
        market_store,
        frame,
        """
        insert or replace into statement_lines
        select
            ticker,
            statement_name,
            timescale,
            line_item,
            line_value,
            cast(period_end as date) as period_end_date,
            current_timestamp as fetched_at
        from frame
        where line_value is not null
        """,
    )
    return len(frame)


def pull_profile(
    market_store: duckdb.DuckDBPyConnection, ticker: str
) -> market.Row:
    """Stores and returns Yahoo's profile (sector, ratios, ...) of a ticker."""
    profile = yfinance.Ticker(ticker).info
    market_store.execute(
        "insert into profiles (ticker, profile, fetched_at)"
        " values (?, ?, current_timestamp)",
        [ticker.upper(), json.dumps(profile, default=str)],
    )
    return profile


def _statement_rows(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    rows = (
        frame.rename_axis("line_item")
        .reset_index()
        .melt(
            id_vars="line_item", var_name="period_end", value_name="line_value"
        )
    )
    rows["statement_name"] = name
    return rows
