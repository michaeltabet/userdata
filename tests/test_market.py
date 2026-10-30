# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Market pulls against stand-ins shaped like edgartools and yfinance output."""

import datetime
import types

import pandas as pd
import pytest

from userdata import market
from userdata import sec
from userdata import yahoo

_FACTS = pd.DataFrame(
    {
        "concept": ["us-gaap:OperatingIncomeLoss", "mt-input:OneOff"] * 2,
        "unit": ["USD"] * 4,
        "numeric_value": [100.0, 10.0, 120.0, 5.0],
        "period_start": [None] * 4,
        "period_end": [datetime.date(2024, 12, 31)] * 2
        + [datetime.date(2025, 12, 31)] * 2,
        "fiscal_year": [2024, 2024, 2025, 2025],
        "fiscal_period": ["FY"] * 4,
        "accession": ["0001-24-000001"] * 2 + ["0001-25-000001"] * 2,
        "filing_date": [datetime.date(2025, 2, 1)] * 2
        + [datetime.date(2026, 2, 1)] * 2,
        "form_type": ["10-K"] * 4,
        "taxonomy": ["us-gaap", "mt-input"] * 2,
    }
)


class _FakeCompany:
    cik = 1234

    def __init__(self, ticker: str) -> None:
        del ticker  # Unused.

    def get_facts(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            to_dataframe=lambda include_metadata: _FACTS.copy()
        )


class _FakeTicker:
    def __init__(self, ticker: str) -> None:
        del ticker  # Unused.

    def history(self, period: str, auto_adjust: bool) -> pd.DataFrame:
        del period, auto_adjust  # Unused.
        index = pd.DatetimeIndex(
            ["2026-10-29", "2026-10-30"], tz="America/New_York", name="Date"
        )
        return pd.DataFrame(
            {
                "Open": [1.0, 2.0],
                "High": [1.0, 2.0],
                "Low": [1.0, 2.0],
                "Close": [1.0, 2.0],
                "Adj Close": [1.0, 2.0],
                "Volume": [10, 20],
                "Dividends": [0.0, 0.0],
                "Stock Splits": [0.0, 0.0],
            },
            index=index,
        )


@pytest.fixture(autouse=True)
def _fake_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sec.edgar, "Company", _FakeCompany)
    monkeypatch.setattr(yahoo.yfinance, "Ticker", _FakeTicker)


def test_pulling_twice_never_doubles(stores):
    _, market_store = stores
    sec.pull_facts(market_store, "X")
    sec.pull_facts(market_store, "X")
    yahoo.pull_prices(market_store, "x", "5d")
    yahoo.pull_prices(market_store, "x", "5d")

    assert market.query(market_store, "select count(*) as n from facts") == [
        {"n": 4}
    ]
    assert market.query(market_store, "select count(*) as n from prices") == [
        {"n": 2}
    ]


def test_own_concept_is_the_weighted_sum_per_period(stores):
    _, market_store = stores
    sec.pull_facts(market_store, "X")
    formula = [
        {"concept": "us-gaap:OperatingIncomeLoss", "weight": 1},
        {"concept": "mt-input:OneOff", "weight": 1},
    ]

    values = market.concept_values(market_store, formula, "1234")

    assert [value["concept_value"] for value in values] == [110.0, 125.0]
    assert [len(value["value_basis"]) for value in values] == [2, 2]


def test_query_refuses_anything_but_one_select(stores):
    _, market_store = stores

    with pytest.raises(ValueError, match="one SELECT"):
        market.query(market_store, "delete from facts")
