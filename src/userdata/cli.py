"""Command line entry point: `userdata migrate`."""

import argparse
import sys

from userdata import config as config_lib
from userdata import engines


def main(argv: list[str] | None = None) -> int:
    """Parses arguments and runs the command.

    Args:
        argv: Arguments without the program name. None means sys.argv.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(prog="userdata")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply pending migrations to both stores")
    args = parser.parse_args(argv)

    config = config_lib.from_env()
    if args.command == "migrate":
        return _migrate(config)
    return 1


def _migrate(config: config_lib.Config) -> int:
    oltp = engines.open_oltp(config)
    olap = engines.open_olap(config)
    try:
        for name in oltp.migrate():
            print(f"oltp applied {name}")
        for name in olap.migrate():
            print(f"olap applied {name}")
    finally:
        oltp.close()
        olap.close()
    print(f"stores: {config.oltp_path} {config.olap_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
