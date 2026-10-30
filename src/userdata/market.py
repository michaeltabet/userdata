# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The DuckDB market store: loading frames, reading rows, own concepts."""

import re
from collections.abc import Sequence
from typing import Any
from typing import TypeAlias

import duckdb
import pandas as pd

Row: TypeAlias = dict[str, Any]


_CONCEPT_SQL = """
with

latest_facts as (
    select
        fact_id,
        concept_name,
        unit_name,
        fact_value,
        period_end_date
    from facts
    where cik = ?
    qualify row_number() over (
        partition by concept_name, unit_name, period_end_date
        order by filed_date desc
    ) = 1
),

input_count as (
    select count(*) as input_count from weights
),

weighted as (
    select
        latest_facts.period_end_date,
        latest_facts.unit_name,
        latest_facts.fact_id,
        latest_facts.fact_value * weights.weight as weighted_value
    from latest_facts
    inner join weights
        on latest_facts.concept_name = weights.concept
),

per_period as (
    select
        cast(period_end_date as varchar) as period_end_date,
        unit_name,
        sum(weighted_value) as concept_value,
        list(fact_id) as value_basis,
        count(*) as inputs_found
    from weighted
    group by 1, 2
),

final as (
    select
        per_period.period_end_date,
        per_period.unit_name,
        per_period.concept_value,
        per_period.value_basis
    from per_period
    inner join input_count
        on per_period.inputs_found = input_count.input_count
)

select * from final
order by 1

"""


def query(market: duckdb.DuckDBPyConnection, sql: str) -> list[Row]:
    """Runs one read-only SELECT on the market store and returns the rows.

    Raises:
        ValueError: If the text is not exactly one SELECT statement.
    """
    statements = market.extract_statements(sql)
    if len(statements) != 1 or (
        statements[0].type != duckdb.StatementType.SELECT
    ):
        raise ValueError("only one SELECT statement is allowed")
    return rows(market.execute(sql))


def concept_values(
    market: duckdb.DuckDBPyConnection, formula: Sequence[Row], cik: str
) -> list[Row]:
    """Computes an own concept from a company's reported facts."""
    market.register("weights", pd.DataFrame(formula))
    try:
        return rows(market.execute(_CONCEPT_SQL, [cik]))
    finally:
        market.unregister("weights")


def load(
    market: duckdb.DuckDBPyConnection, frame: pd.DataFrame, sql: str
) -> None:
    """Runs an insert that reads the frame as the table `frame`."""
    market.register("frame", frame)
    try:
        market.execute(sql)
    finally:
        market.unregister("frame")


def rows(cursor: duckdb.DuckDBPyConnection) -> list[Row]:
    """Returns a query's result as dicts keyed by column name."""
    columns = [column[0] for column in cursor.description or []]
    return [
        dict(zip(columns, values, strict=True)) for values in cursor.fetchall()
    ]


def snake_case(frame: pd.DataFrame) -> pd.DataFrame:
    """Renames columns like "Adj Close" or "reportDate" to snake_case."""
    renamed = {
        column: re.sub(r"(?<=[a-z])(?=[A-Z])", "_", column)
        .replace(" ", "_")
        .lower()
        for column in frame.columns
    }
    return frame.rename(columns=renamed)
