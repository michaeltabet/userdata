# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The open stores, handed to every tool call through the lifespan state."""

import dataclasses
import sqlite3

import duckdb
from mcp.server.mcpserver import Context

from userdata import config as config_lib


@dataclasses.dataclass(frozen=True)
class Stores:
    """The open stores, handed to every tool call."""

    config: config_lib.Config
    account: sqlite3.Connection
    market: duckdb.DuckDBPyConnection


def of(context: Context) -> Stores:
    """Returns the stores of the server handling this tool call."""
    stores = context.request_context.lifespan_context
    if not isinstance(stores, Stores):
        raise TypeError(f"unexpected lifespan state: {type(stores)=}")
    return stores
