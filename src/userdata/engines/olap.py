"""The analytical engine: DuckDB now, ClickHouse later (SDD section 8.2).

One process owns the DuckDB file for writing. Other readers open it
read-only.
"""

import contextlib
import pathlib
from collections.abc import Iterator
from collections.abc import Sequence
from typing import Any
from typing import Protocol

import duckdb

from userdata import config as config_lib
from userdata import ids

_MIGRATIONS = (
    pathlib.Path(__file__).resolve().parents[3] / "migrations" / "olap"
)


class OlapEngine(Protocol):
    """What the OLAP repositories are allowed to call."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
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
        """Opens a transaction that commits on exit, rolls back on error.

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


class DuckDbEngine:
    """DuckDB on a single file."""

    def __init__(
        self, config: config_lib.Config, read_only: bool = False
    ) -> None:
        """Opens or creates the analytics file.

        Args:
            config: Where the file lives and how wide vectors are.
            read_only: Open without the write lock, for a second process.
        """
        config.ensure_dirs()
        self.path = config.olap_path
        self.embed_dim = config.embed_dim
        self._conn = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            self.path.chmod(0o600)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        """Runs one statement and returns all rows.

        Args:
            sql: One SQL statement with placeholders.
            params: Values for the placeholders.

        Returns:
            Every result row as a tuple.
        """
        return self._conn.execute(sql, list(params)).fetchall()

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Runs one statement once per row.

        Args:
            sql: One SQL statement with placeholders.
            rows: One sequence of values per execution.
        """
        if rows:
            self._conn.executemany(sql, [list(r) for r in rows])

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Opens a transaction that commits on exit, rolls back on error.

        Yields:
            None, inside the open transaction.
        """
        self._conn.begin()
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def migrate(self) -> list[str]:
        """Applies migrations/olap/NNNN_*.sql that are not yet recorded.

        The token `{EMBED_DIM}` in a file is replaced by the configured
        vector width.

        Returns:
            The stems of the files applied, in order.
        """
        self._conn.execute(
            "create table if not exists schema_migration ("
            " version integer primary key,"
            " name varchar not null,"
            " applied_at timestamp not null)"
        )
        done = {
            row[0]
            for row in self._conn.execute(
                "select version from schema_migration"
            ).fetchall()
        }
        applied: list[str] = []
        for path in sorted(_MIGRATIONS.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in done:
                continue
            script = path.read_text().replace(
                "{EMBED_DIM}", str(self.embed_dim)
            )
            with self.transaction():
                for statement in _split(script):
                    self._conn.execute(statement)
                self._conn.execute(
                    "insert into schema_migration values (?, ?, ?)",
                    [version, path.stem, ids.now_iso()],
                )
            applied.append(path.stem)
        return applied

    def close(self) -> None:
        """Closes the connection."""
        self._conn.close()


def _split(script: str) -> list[str]:
    """Splits a migration into statements on a ';' that ends a line.

    The OLAP schema has no triggers or procedures, so this is safe.

    Args:
        script: The whole file.

    Returns:
        The statements, comments and blank lines removed.
    """
    statements: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements
