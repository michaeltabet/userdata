# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Pulls from SEC EDGAR, through edgartools, into the market store."""

import json

import duckdb
import edgar

from userdata import market


def pull_company(
    market_store: duckdb.DuckDBPyConnection, ticker: str
) -> market.Row:
    """Stores a company's SEC profile and returns it, CIK included."""
    data = edgar.Company(ticker).data
    company = {
        "cik": str(data.cik),
        "company_name": data.name,
        "sic_code": data.sic,
        "fiscal_year_end": data.fiscal_year_end,
        "tickers": json.dumps(data.tickers),
        "exchanges": json.dumps(data.exchanges),
    }
    market_store.execute(
        "insert or replace into companies (cik, company_name, sic_code,"
        " fiscal_year_end, tickers, exchanges, fetched_at)"
        " values (?, ?, ?, ?, ?, ?, current_timestamp)",
        list(company.values()),
    )
    return company


def pull_filings(
    market_store: duckdb.DuckDBPyConnection,
    ticker: str,
    form_type: str,
    limit: int,
) -> int:
    """Stores the latest filings of one form type; returns how many."""
    company = edgar.Company(ticker)
    frame = company.get_filings(form=form_type).head(limit).data.to_pandas()
    frame = market.snake_case(frame)
    frame["cik"] = str(company.cik)
    market.load(
        market_store,
        frame,
        """
        insert or replace into filings
        select
            accession_number,
            cik,
            form as form_type,
            primary_document,
            items as filing_items,
            filing_date as filed_date,
            try_cast(report_date as date) as report_date,
            acceptance_date_time as accepted_at,
            current_timestamp as fetched_at
        from frame
        """,
    )
    return len(frame)


def pull_facts(market_store: duckdb.DuckDBPyConnection, ticker: str) -> int:
    """Stores every XBRL fact SEC holds for a company; returns how many."""
    company = edgar.Company(ticker)
    entity_facts = company.get_facts()
    if entity_facts is None:
        raise ValueError(f"SEC holds no XBRL facts for {ticker=}")
    frame = entity_facts.to_dataframe(include_metadata=True)
    frame["cik"] = str(company.cik)
    market.load(
        market_store,
        frame,
        """
        insert or replace into facts
        select
            md5(
                concat_ws(
                    '|',
                    cik,
                    accession,
                    concept,
                    unit,
                    period_start,
                    period_end,
                    fiscal_period
                )
            ) as fact_id,
            cik,
            accession as accession_number,
            taxonomy as taxonomy_name,
            concept as concept_name,
            unit as unit_name,
            fiscal_period,
            form_type,
            fiscal_year,
            numeric_value as fact_value,
            period_start as period_start_date,
            period_end as period_end_date,
            filing_date as filed_date,
            current_timestamp as fetched_at
        from frame
        qualify row_number() over (partition by fact_id) = 1
        """,
    )
    return len(frame)
