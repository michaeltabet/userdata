# USERDATA

The tools exist. The user has no data store. USERDATA is that store.

A logged-in Yahoo Finance account remembers your history, screens and
watchlists. USERDATA is that account for equity research done with Claude,
built properly: one MCP server that keeps every session, preference, skill,
tag, custom XBRL concept, watchlist, peer group, note, thesis and research
step, plus every number and filing pulled from SEC EDGAR and Yahoo Finance,
with each number traceable to the filing it came from.

## Status

v1 works: 23 MCP tools over two stores, pulling real SEC and Yahoo data.
Every file is under 150 lines and passes Google's pylint, pyrefly and
dbt's SQLFluff rules.

## Run

```sh
cp userdata.example.toml userdata.toml   # edit paths and contact
make setup test lint
USERDATA_CONFIG=$PWD/userdata.toml uv run userdata serve          # stdio
USERDATA_CONFIG=$PWD/userdata.toml uv run userdata serve --http   # HTTP
```

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
