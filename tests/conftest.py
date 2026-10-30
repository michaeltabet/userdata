"""Shared fixtures: a fresh data directory and migrated stores per test."""

import pathlib
from collections.abc import Iterator

import pytest

from userdata import config
from userdata import engines
from userdata.engines import olap
from userdata.engines import oltp


@pytest.fixture
def cfg(tmp_path: pathlib.Path) -> config.Config:
    """Returns a Config whose data directory is the test's tmp_path.

    Args:
        tmp_path: The pytest temporary directory.

    Returns:
        The configuration.
    """
    return config.Config(data_dir=tmp_path / "data")


@pytest.fixture
def store(cfg: config.Config) -> Iterator[oltp.OltpEngine]:
    """Yields a migrated SQLite engine and closes it afterwards.

    Args:
        cfg: The test configuration.

    Yields:
        The OLTP engine.
    """
    engine = engines.open_oltp(cfg)
    engine.migrate()
    yield engine
    engine.close()


@pytest.fixture
def analytics(cfg: config.Config) -> Iterator[olap.OlapEngine]:
    """Yields a migrated DuckDB engine and closes it afterwards.

    Args:
        cfg: The test configuration.

    Yields:
        The OLAP engine.
    """
    engine = engines.open_olap(cfg)
    engine.migrate()
    yield engine
    engine.close()
