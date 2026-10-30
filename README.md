# USERDATA

The tools exist. The user has no data store. USERDATA is that store.

A logged-in Yahoo Finance account remembers your history, screens and
watchlists. USERDATA is that account for equity research done with Claude,
built properly: one MCP server that keeps every session, preference, skill,
tag, custom XBRL concept, watchlist, peer group, note, thesis and research
step, plus every number and filing pulled from SEC EDGAR and Yahoo Finance,
with each number traceable to the filing it came from.

## Status

Phase 0 of v1: the two database schemas, migrations, invariants and the
kill-and-restart persistence proof. The MCP tool layer and the deployment
come next. See [docs/SDD.md](docs/SDD.md).

## Design in one paragraph

Two stores. SQLite holds the record: everything a person or Claude authored,
written as an append-only event log with projections, plus reference data
and the cache index. DuckDB holds derived data: facts, prices, chunks,
embeddings, ratios, rebuilt from immutable raw payloads plus the event log
plus a code version. Postgres and ClickHouse replace them later with no
schema rework. Modelling follows Kleppmann's *Designing Data-Intensive
Applications*; every table in the SDD states its access pattern, row
volume and why it is shaped the way it is.

## Documents

| File | What |
|---|---|
| [docs/SDD.md](docs/SDD.md) | Software design: load, use cases, the record/derived rule, ERD with rationale, sequence diagrams, invariants, physical design |
| [docs/DATA-CATALOGUE.md](docs/DATA-CATALOGUE.md) | Every field `edgartools` and `yfinance` return, and where it lands |
| [docs/SCHEMA.md](docs/SCHEMA.md) | Generated table list, one line per table; the build fails if it drifts |
| [docs/REVIEW-1.md](docs/REVIEW-1.md) | Independent DDIA review of draft 1, and what it changed |

The Markdown has Mermaid diagrams. GitHub renders them. Locally,
`uv run python scripts/render_docs.py docs/SDD.md` writes an HTML copy.

## Run

Requires Python 3.14 and [uv](https://github.com/astral-sh/uv).

```sh
make setup       # uv sync
make migrate     # creates ~/Slop/userdata-data/{store.db,analytics.duckdb}
make test        # pytest, including the kill-and-restart proof
make lint        # ruff, Google Python style
make licenses    # fails on any non-permissive dependency
```

`USERDATA_DIR` moves the data directory. `USERDATA_OLTP` and `USERDATA_OLAP`
name the engines; v1 accepts `sqlite` and `duckdb`.

## Sources

Built on [edgartools](https://github.com/dgunning/edgartools) (MIT) and
[yfinance](https://github.com/ranaroussi/yfinance) (Apache-2.0). Arelle
(Apache-2.0) validates custom taxonomies and builds the iXBRL viewer.

## Rules

- Permissive licences only. CI fails on anything else.
- Every write survives a kill and a restart, vectors included.
- No engine name inside a tool. Engine choice is configuration.
- Additive schema changes only.
- Python: Google style guide. SQL: dbt style guide.

## Licence

MIT. See [LICENSE](LICENSE).
