# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Settings, read from a TOML file named by USERDATA_CONFIG."""

import dataclasses
import os
import pathlib
import tomllib


@dataclasses.dataclass(frozen=True)
class Config:
    """The settings file, as values."""

    data_dir: pathlib.Path
    host: str
    port: int
    sec_user_agent: str
    public_url: str
    auth_issuer: str
    auth_audience: str

    @property
    def account_path(self) -> pathlib.Path:
        """The SQLite file."""
        return self.data_dir / "account.db"

    @property
    def market_path(self) -> pathlib.Path:
        """The DuckDB file."""
        return self.data_dir / "market.duckdb"


def load(path: pathlib.Path | None = None) -> Config:
    """Reads the settings file."""
    if path is None:
        path = pathlib.Path(os.environ["USERDATA_CONFIG"])
    values = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(
        data_dir=pathlib.Path(values["data_dir"]).expanduser(),
        host=values["host"],
        port=values["port"],
        sec_user_agent=values["sec_user_agent"],
        public_url=values["public_url"],
        auth_issuer=values.get("auth_issuer", ""),
        auth_audience=values.get("auth_audience", ""),
    )
