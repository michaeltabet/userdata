# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Everything written survives the process being killed mid-flight."""

import os
import signal
import subprocess
import sys
import textwrap

from userdata import account
from userdata import config as config_lib
from userdata import stores

_WRITER = textwrap.dedent(
    """\
    import pathlib, sys, time
    from userdata import account, config, stores
    settings = config.Config(
        pathlib.Path(sys.argv[1]), "127.0.0.1", 0, "test", "http://test", "", ""
    )
    with stores.open_stores(settings) as (account_store, market_store):
        note = {"note_id": "1", "note_text": "survives", "created_at": "t"}
        account.save(account_store, "notes", note, "note_added")
        market_store.execute(
            "insert into prices (ticker, trade_date, fetched_at)"
            " values ('AEP', date '2026-10-30', current_timestamp)"
        )
        market_store.execute("checkpoint")
        print("written", flush=True)
        time.sleep(60)
    """
)


def test_writes_survive_a_kill(config: config_lib.Config):
    writer = subprocess.Popen(
        [sys.executable, "-c", _WRITER, str(config.data_dir)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert writer.stdout.readline().strip() == "written"
    os.kill(writer.pid, signal.SIGKILL)
    writer.wait()

    with stores.open_stores(config) as (account_store, market_store):
        notes = account_store.execute("select note_text from notes").fetchall()
        prices = market_store.execute("select ticker from prices").fetchall()
        events = account.history(account_store)

    assert [row[0] for row in notes] == ["survives"]
    assert prices == [("AEP",)]
    assert events[0]["event_type"] == "note_added"
