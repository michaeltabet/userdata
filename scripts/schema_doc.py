"""Writes docs/SCHEMA.md from the migration DDL so it never drifts.

Each `create table` in migrations/*/NNNN_*.sql must be preceded by a comment
line `-- <kind>: <purpose>`. The natural key is read from the primary key and
unique constraints; for a hashed id, from the `sha256(...)` comment beside it.

Usage:
    uv run python scripts/schema_doc.py          # rewrite docs/SCHEMA.md
    uv run python scripts/schema_doc.py --check  # exit 1 if it is stale
"""

import argparse
import dataclasses
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_STORES = (("sqlite", "oltp"), ("duckdb", "olap"))
_KIND = re.compile(r"^-- (sor|projection|reference|derived|view): (.+)$")
_VIEW = re.compile(r"^create view (\w+) as$")
_CREATE = re.compile(r"^create table (\w+) \($")
_COLUMN = re.compile(r"^\s{4}(\w+) \w+")
_INLINE_COMMENT = re.compile(r"--\s*(.+)$")


@dataclasses.dataclass
class Table:
    """One table as documented.

    Attributes:
        store: sqlite or duckdb.
        name: Table name.
        kind: sor, projection, reference, derived or view.
        primary_key: Primary-key columns in order; empty for a view.
        uniques: Each unique constraint's columns.
        key_note: The sha256(...) or format comment of a one-column key;
            for a view, its purpose.
    """

    store: str
    name: str
    kind: str
    primary_key: list[str] = dataclasses.field(default_factory=list)
    uniques: list[list[str]] = dataclasses.field(default_factory=list)
    key_note: str = ""

    def natural_key(self) -> str:
        """Formats the natural key for the table.

        Returns:
            The key as Markdown text.
        """
        if self.kind == "view":
            return self.key_note
        key = ", ".join(self.primary_key)
        parts = [f"`{key}`"]
        if self.key_note:
            parts[0] += f" = {self.key_note}"
        parts.extend(f"unique `{', '.join(u)}`" for u in self.uniques)
        return "; ".join(parts)


def _columns(text: str) -> list[str]:
    """Splits a parenthesised column list.

    Args:
        text: Text containing `( a, b )`, possibly over several lines.

    Returns:
        The column names.
    """
    inner = text[text.index("(") + 1 : text.rindex(")")]
    return [c.strip() for c in inner.split(",") if c.strip()]


def _key_note(above: list[str], line: str) -> str:
    """Returns the comment that explains a one-column key, if any.

    Args:
        above: The table's lines before the key column, nearest last.
        line: The key column line.

    Returns:
        The inline comment, else the first line of the comment block right
        above the column, else the empty string.
    """
    inline = _INLINE_COMMENT.search(line)
    if inline:
        return inline.group(1).strip()
    block: list[str] = []
    for previous in reversed(above):
        if not previous.strip().startswith("--"):
            break
        block.insert(0, previous.strip().removeprefix("--").strip())
    return block[0].rstrip(":") if block else ""


def _kind_of(lines: list[str], i: int) -> re.Match[str] | None:
    """Finds the kind comment in the comment block above line i.

    Args:
        lines: The file's lines.
        i: Index of the `create` line.

    Returns:
        The match of the first `-- <kind>: <purpose>` line, or None.
    """
    j = i - 1
    while j >= 0 and lines[j].startswith("--"):
        j -= 1
    for line in lines[j + 1 : i]:
        match = _KIND.match(line)
        if match:
            return match
    return None


def parse(path: pathlib.Path, store: str) -> list[Table]:
    """Reads the tables of one migration file.

    Args:
        path: The .sql file.
        store: The store name to record.

    Returns:
        The tables in file order.

    Raises:
        ValueError: If a table has no kind comment or no primary key.
    """
    lines = path.read_text().splitlines()
    tables: list[Table] = []
    i = 0
    while i < len(lines):
        view = _VIEW.match(lines[i])
        if view:
            kind = _kind_of(lines, i)
            if not kind or kind.group(1) != "view":
                raise ValueError(f"{path.name}: {view.group(1)} lacks a kind")
            tables.append(
                Table(store, view.group(1), "view", key_note=kind.group(2))
            )
            i += 1
            continue
        match = _CREATE.match(lines[i])
        if not match:
            i += 1
            continue
        kind = _kind_of(lines, i)
        if not kind:
            raise ValueError(f"{path.name}: {match.group(1)} lacks a kind")
        table = Table(store, match.group(1), kind.group(1))
        start = i + 1
        i += 1
        while lines[i] != ");":
            line = lines[i]
            body = line.split("--", 1)[0]
            stripped = body.strip()
            if stripped.startswith(("primary key", "unique")):
                block = stripped
                while block.count("(") > block.count(")"):
                    i += 1
                    block += lines[i].split("--", 1)[0].strip()
                columns = _columns(block)
                if block.startswith("primary key"):
                    table.primary_key = columns
                else:
                    table.uniques.append(columns)
            else:
                column = _COLUMN.match(body)
                if column and " primary key" in body:
                    table.primary_key = [column.group(1)]
                    table.key_note = _key_note(lines[start:i], line)
                elif column and re.search(r"\bunique\b", body):
                    table.uniques.append([column.group(1)])
            i += 1
        if not table.primary_key:
            raise ValueError(f"{path.name}: {table.name} has no primary key")
        tables.append(table)
    return tables


def render(tables: list[Table]) -> str:
    """Renders the Markdown document.

    Args:
        tables: Every table of both stores.

    Returns:
        The file contents.
    """
    out = [
        "# Schema",
        "",
        "Generated by `scripts/schema_doc.py` from `migrations/`. "
        "Do not edit by hand. For a view, the last column says what it "
        "selects.",
        "",
        "| Store | Table | Kind | Natural key |",
        "|---|---|---|---|",
    ]
    for t in tables:
        key = t.natural_key().replace("|", "\\|")
        out.append(f"| {t.store} | `{t.name}` | {t.kind} | {key} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Writes or checks docs/SCHEMA.md.

    Args:
        argv: Arguments without the program name. None means sys.argv.

    Returns:
        The process exit code: 1 when --check finds the file stale.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    tables: list[Table] = []
    for store, folder in _STORES:
        for path in sorted((_ROOT / "migrations" / folder).glob("*.sql")):
            tables.extend(parse(path, store))
    text = render(tables)
    target = _ROOT / "docs" / "SCHEMA.md"
    if args.check:
        current = target.read_text() if target.exists() else ""
        if current != text:
            print(f"{target} is stale; run scripts/schema_doc.py")
            return 1
        return 0
    target.write_text(text)
    print(f"wrote {target} ({len(tables)} tables and views)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
