# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Command line: `userdata serve` (stdio) or `userdata serve --http`."""

import argparse

import edgar

from userdata import config as config_lib
from userdata import server


def main() -> None:
    """Serves the tools until stopped."""
    parser = argparse.ArgumentParser(prog="userdata")
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--http", action="store_true", help="serve over HTTP")
    arguments = parser.parse_args()

    config = config_lib.load()
    edgar.set_identity(config.sec_user_agent)
    mcp_server = server.build_server(config)
    if arguments.http:
        mcp_server.run("streamable-http", host=config.host, port=config.port)
    else:
        mcp_server.run("stdio")


if __name__ == "__main__":
    main()
