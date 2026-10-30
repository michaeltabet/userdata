"""Configuration.

Engine names and paths come from here and nowhere else (SDD rule 3).
"""

import dataclasses
import os
import pathlib

_DEFAULT_DIR = pathlib.Path.home() / "Slop" / "userdata-data"


@dataclasses.dataclass(frozen=True)
class Config:
    """Where and how data is stored.

    Attributes:
        data_dir: Root directory, created with mode 0o700.
        oltp_engine: Transactional engine name. v1 supports "sqlite".
        olap_engine: Analytical engine name. v1 supports "duckdb".
        embed_model: Sentence-transformers model for chunk embeddings.
        embed_dim: Vector width. Must match the OLAP schema.
    """

    data_dir: pathlib.Path = _DEFAULT_DIR
    oltp_engine: str = "sqlite"
    olap_engine: str = "duckdb"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: int = 384

    @property
    def oltp_path(self) -> pathlib.Path:
        """Path of the SQLite file."""
        return self.data_dir / "store.db"

    @property
    def olap_path(self) -> pathlib.Path:
        """Path of the DuckDB file."""
        return self.data_dir / "analytics.duckdb"

    @property
    def raw_dir(self) -> pathlib.Path:
        """Directory of immutable source payloads."""
        return self.data_dir / "raw"

    @property
    def taxonomy_dir(self) -> pathlib.Path:
        """Directory where taxonomy files are exported for Arelle."""
        return self.data_dir / "taxonomy"

    def ensure_dirs(self) -> None:
        """Creates the data directories with owner-only permissions."""
        for path in (self.data_dir, self.raw_dir, self.taxonomy_dir):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)


def from_env() -> Config:
    """Builds a Config from USERDATA_* environment variables.

    Returns:
        A Config with defaults for anything not set.
    """
    data_dir = pathlib.Path(
        os.environ.get("USERDATA_DIR", str(_DEFAULT_DIR))
    ).expanduser()
    return Config(
        data_dir=data_dir,
        oltp_engine=os.environ.get("USERDATA_OLTP", "sqlite"),
        olap_engine=os.environ.get("USERDATA_OLAP", "duckdb"),
        embed_model=os.environ.get("USERDATA_EMBED_MODEL", Config.embed_model),
        embed_dim=int(os.environ.get("USERDATA_EMBED_DIM", Config.embed_dim)),
    )
