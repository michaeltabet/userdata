# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""The MCP server: its sign-in and its tools, bound to the open stores."""

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from mcp import server as mcp_server
from mcp.server.auth import settings

from userdata import account_tools
from userdata import config as config_lib
from userdata import list_tools
from userdata import market_tools
from userdata import research_tools
from userdata import stores
from userdata import tokens

_INSTRUCTIONS = """\
USERDATA is Michael's research account. At the start of work call
start_session (inside a project if there is one) and record what you do
with log. Use history to answer "what did we do". Pull data before querying
it. Tag filings by accession number and facts by fact_id."""


def build_server(config: config_lib.Config) -> mcp_server.MCPServer:
    """Returns the server; the stores open when it starts and close after."""

    @contextlib.asynccontextmanager
    async def lifespan(
        server: mcp_server.MCPServer,
    ) -> AsyncIterator[stores.Stores]:
        del server  # Unused.
        with stores.open_stores(config) as (account_store, market_store):
            yield stores.Stores(config, account_store, market_store)

    server = mcp_server.MCPServer(
        "userdata",
        instructions=_INSTRUCTIONS,
        lifespan=lifespan,
        **_auth_settings(config),
    )
    for tool_function in (
        account_tools.TOOLS
        + list_tools.TOOLS
        + research_tools.TOOLS
        + market_tools.TOOLS
    ):
        server.add_tool(tool_function)
    return server


def _auth_settings(config: config_lib.Config) -> dict[str, Any]:
    if not config.auth_issuer:
        return {}
    verifier = tokens.AuthentikVerifier(
        config.auth_issuer, config.auth_audience
    )
    return {
        "token_verifier": verifier,
        "auth": settings.AuthSettings(
            issuer_url=config.auth_issuer,
            resource_server_url=f"{config.public_url}/mcp",
            required_scopes=[tokens.SCOPE],
        ),
    }
