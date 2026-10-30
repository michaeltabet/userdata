# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""A working session driven only through the MCP tools, as Claude would."""

import asyncio
import json

from mcp import types
from mcp.client import session as client_session
from mcp.shared import memory

from userdata import server


async def _run_session(config):
    mcp_server = server.build_server(config)
    # The SDK exposes no public in-memory runner.
    lowlevel = mcp_server._lowlevel_server  # pylint: disable=protected-access
    async with memory.create_client_server_memory_streams() as streams:
        client_streams, server_streams = streams
        serving = asyncio.create_task(
            lowlevel.run(
                *server_streams, lowlevel.create_initialization_options()
            )
        )
        async with client_session.ClientSession(*client_streams) as client:
            await client.initialize()
            await client.call_tool("start_session", {"session_title": "today"})
            await client.call_tool(
                "create_list",
                {
                    "list_name": "w",
                    "list_type": "watchlist",
                    "purpose_text": "",
                },
            )
            await client.call_tool(
                "add_to_list",
                {"list_name": "w", "ticker": "aep", "reason_text": "cheap"},
            )
            answer = await client.call_tool(
                "query_account", {"sql": "select ticker from list_members"}
            )
        serving.cancel()
    return answer


def test_a_session_through_the_tools(config):
    answer = asyncio.run(_run_session(config))

    assert isinstance(answer.content[0], types.TextContent)
    assert json.loads(answer.content[0].text) == {"ticker": "AEP"}
