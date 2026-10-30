"""The transactional engine: SQLite now, Postgres later (SDD section 8.1)."""

import contextlib
import pathlib
import sqlite3
from collections.abc import Iterator
from collections.abc import Sequence
from typing import Any
from typing import Protocol

from userdata import config as config_lib
from userdata import ids

_MIGRATIONS = (
    pathlib.Path(__file__).resolve().parents[3] / "migrations" / "oltp"
)


class OltpEngine(Protocol):
    """What the OLTP repositories are allowed to call."""

    def execute(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> list[tuple]:
        """Runs one statement and returns all rows.

        Args:
            sql: One SQL statement with placeholders.
            params: Values for the placeholders.

        Returns:
            Every result row as a tuple.
        """
        ...

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Runs one statement once per row.

        Args:
            sql: One SQL statement with placeholders.
            rows: One sequence of values per execution.
        """
        ...

    def transaction(self) -> contextlib.AbstractContextManager[None]:
        """Opens a write transaction; commits on exit, rolls back on error.

        Returns:
            A context manager for the transaction.
        """
        ...

    def migrate(self) -> list[str]:
        """Applies pending migrations.

        Returns:
            The names applied, in order.
        """
        ...

    def close(self) -> None:
        """Closes the connection."""
        ...


class SqliteEngine:
    """SQLite with WAL, full sync, foreign keys and up-front write locks.

    `BEGIN IMMEDIATE` takes the write lock at the start of a transaction, so
    a read-then-write never fails with SQLITE_BUSY halfway (SDD section 7).
    """

    def __init__(self, config: config_lib.Config) -> None:
        """Opens or creates the store file.

        Args:
            config: Where the file lives.
        """
        config.ensure_dirs()
        self.path = config.oltp_path
        self._conn = sqlite3.connect(
            self.path, isolation_level=None, timeout=30
        )
        self.path.chmod(0o600)
        self._conn.execute("pragma journal_mode = wal")
        self._conn.execute("pragma synchronous = full")
        self._conn.execute("pragma foreign_keys = on")
        self._conn.execute("pragma busy_timeout = 30000")

    def execute(
        self, sql: str, params: Sequence[Any] | dict[str, Any] = ()
    ) -> list[tuple]:
        """Runs one statement and returns all rows.

        Args:
            sql: One SQL statement with placeholders.
            params: Values for the placeholders.

        Returns:
            Every result row as a tuple.
        """
        return self._conn.execute(sql, params).fetchall()

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Runs one statement once per row.

        Args:
            sql: One SQL statement with placeholders.
            rows: One sequence of values per execution.
        """
        self._conn.executemany(sql, rows)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Opens a write transaction; commits on exit, rolls back on error.

        Yields:
            None, inside the open transaction.
        """
        self._conn.execute("begin immediate")
        try:
            yield
        except BaseException:
            self._conn.execute("rollback")
            raise
        else:
            self._conn.execute("commit")

    def migrate(self) -> list[str]:
        """Applies migrations/oltp/NNNN_*.sql that are not yet recorded.

        Each file runs in its own transaction together with its
        schema_migration row, so a failed migration leaves no trace.

        Returns:
            The stems of the files applied, in order.

        Raises:
            sqlite3.Error: If a migration fails; it is rolled back first.
        """
        self._conn.execute(
            "create table if not exists schema_migration ("
            " version integer primary key,"
            " name text not null,"
            " applied_at text not null)"
        )
        done = {
            row[0]
            for row in self._conn.execute(
                "select version from schema_migration"
            )
        }
        applied: list[str] = []
        for path in sorted(_MIGRATIONS.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in done:
                continue
            record = (
                "insert into schema_migration (version, name, applied_at)"
                f" values ({version}, '{path.stem}', '{ids.now_iso()}');"
            )
            script = "begin immediate;\n" + path.read_text() + "\n" + record
            script += "\ncommit;"
            try:
                self._conn.executescript(script)
            except sqlite3.Error:
                # executescript stops at the failing statement and leaves the
                # transaction open; roll back so nothing of it remains.
                if self._conn.in_transaction:
                    self._conn.execute("rollback")
                raise
            applied.append(path.stem)
        return applied

    def close(self) -> None:
        """Closes the connection."""
        self._conn.close()
