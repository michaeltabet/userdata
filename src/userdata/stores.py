# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The two stores: opening them, migrating them, handing them to tools."""

import contextlib
import dataclasses
import pathlib
import sqlite3
from collections.abc import Iterator

import duckdb
from mcp.server import mcpserver

from userdata import config as config_lib

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"


@contextlib.contextmanager
def open_stores(
    config: config_lib.Config,
) -> Iterator[tuple[sqlite3.Connection, duckdb.DuckDBPyConnection]]:
    """Opens both stores, migrated, and closes them on exit."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.chmod(0o700)
    account = sqlite3.connect(config.account_path, autocommit=True)
    account.row_factory = sqlite3.Row
    account.execute("pragma journal_mode = wal")
    account.execute("pragma synchronous = full")
    account.execute("pragma foreign_keys = on")
    market = duckdb.connect(str(config.market_path))
    try:
        _migrate_account(account)
        _migrate_market(market)
        yield account, market
    finally:
        account.close()
        market.close()


@contextlib.contextmanager
def transaction(account: sqlite3.Connection) -> Iterator[None]:
    """Runs the block as one write transaction on the account store."""
    account.execute("begin immediate")
    try:
        yield
    except BaseException:
        account.execute("rollback")
        raise
    account.execute("commit")


def _migrate_account(account: sqlite3.Connection) -> None:
    for path in _pending(account, "account"):
        script = path.read_text(encoding="utf-8")
        account.executescript(
            f"begin;\n{script}\n"
            "insert into schema_migrations"
            f" values ('{path.stem}', current_timestamp);\ncommit;"
        )


def _migrate_market(market: duckdb.DuckDBPyConnection) -> None:
    for path in _pending(market, "market"):
        market.begin()
        market.execute(path.read_text(encoding="utf-8"))
        market.execute(
            "insert into schema_migrations values (?, current_timestamp)",
            [path.stem],
        )
        market.commit()


def _pending(
    connection: sqlite3.Connection | duckdb.DuckDBPyConnection, store: str
) -> list[pathlib.Path]:
    connection.execute(
        "create table if not exists schema_migrations ("
        "migration_name varchar primary key, applied_at varchar not null)"
    )
    applied = {
        row[0]
        for row in connection.execute(
            "select migration_name from schema_migrations"
        ).fetchall()
    }
    return [
        path
        for path in sorted((_MIGRATIONS / store).glob("*.sql"))
        if path.stem not in applied
    ]


@dataclasses.dataclass(frozen=True)
class Stores:
    """The open stores, handed to every tool call.

    Attributes:
        config: The settings the server started with.
        account: The SQLite account store.
        market: The DuckDB market store.
    """

    config: config_lib.Config
    account: sqlite3.Connection
    market: duckdb.DuckDBPyConnection


def from_context(context: mcpserver.Context) -> Stores:
    """Returns the stores of the server handling this tool call.

    Raises:
        TypeError: If the server was not started by `server.build_server`.
    """
    stores = context.request_context.lifespan_context
    if not isinstance(stores, Stores):
        raise TypeError(f"unexpected lifespan state: {type(stores)=}")
    return stores
