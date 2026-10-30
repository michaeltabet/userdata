# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Fixtures: both stores, empty and migrated, in a temporary directory."""

import pathlib

import pytest

from userdata import config as config_lib
from userdata import stores


@pytest.fixture(name="config")
def config_fixture(tmp_path: pathlib.Path) -> config_lib.Config:
    return config_lib.Config(
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,
        sec_user_agent="test",
        public_url="http://test",
        auth_issuer="",
        auth_audience="",
    )


@pytest.fixture(name="stores")
def stores_fixture(config: config_lib.Config):
    with stores.open_stores(config) as opened:
        yield opened
