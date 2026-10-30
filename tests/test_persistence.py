"""SDD rule 2: every committed write survives a kill and restart.

A child process commits rows to both stores, reports that it committed, and
is killed with SIGKILL before it can close anything. The parent then opens
both stores with fresh engines and finds every row.
"""

import os
import pathlib
import signal
import subprocess
import sys

from userdata import config
from userdata import engines

_DIM = 384

_CHILD = """
import sys
import time

from userdata import config
from userdata import engines

cfg = config.from_env()
store = engines.open_oltp(cfg)
analytics = engines.open_olap(cfg)
store.migrate()
analytics.migrate()
now = "2026-10-30T12:00:00Z"
with store.transaction():
    store.execute(
        "insert into event (event_id, stream, stream_seq, type, payload,"
        " payload_schema, actor_id, recorded_at) values ('ev-1',"
        " 'preference:global', 1, 'preference_set', '{\\"v\\": 1}',"
        " 'preference_set@1', 'claude', ?)",
        (now,),
    )
    store.execute(
        "insert into session (session_id, actor_id, client, started_at,"
        " context_schema) values ('se-1', 'claude', 'claude-code', ?,"
        " 'session-context@1')",
        (now,),
    )
    store.execute(
        "insert into preference_current (scope, key, value, value_schema,"
        " event_id, updated_at) values ('global', 'units', '\\"usd_m\\"',"
        " 'units@1', 'ev-1', ?)",
        (now,),
    )
vector = [float(i % 17) - 8.0 for i in range(cfg.embed_dim)]
with analytics.transaction():
    analytics.execute(
        "insert into fact (fact_row_id, origin, source, issuer_id,"
        " concept_id, period_end, unit, dimensions_schema, value,"
        " statement_basis, known_at, known_at_precision, code_version,"
        " load_batch_id) values ('fa-1', 'reported', 'edgar',"
        " 'cik:0000000001', 'us-gaap:Revenues', '2025-12-31', 'USD',"
        " 'dimensions@1', 1234.5, 'as_reported', ?, 'datetime', 'test@1',"
        " 'lb-1')",
        (now,),
    )
    analytics.execute(
        "insert into chunk_embedding (chunk_id, model, chunker_version, dim,"
        " vector, document_id, created_at) values ('ch-1', 'm', 'c1', ?,"
        f" ?::float[{cfg.embed_dim}], 'doc-1', ?)",
        (cfg.embed_dim, vector, now),
    )
print("committed", flush=True)
time.sleep(120)
sys.exit(1)
"""


def _vector() -> list[float]:
    """Returns the vector the child writes.

    Returns:
        A 384-float list.
    """
    return [float(i % 17) - 8.0 for i in range(_DIM)]


def test_committed_rows_survive_sigkill(tmp_path: pathlib.Path) -> None:
    """Rows committed by a SIGKILLed process are all there on reopen."""
    data_dir = tmp_path / "data"
    env = {**os.environ, "USERDATA_DIR": str(data_dir)}
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "committed"
        child.send_signal(signal.SIGKILL)
        assert child.wait(timeout=30) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

    cfg = config.Config(data_dir=data_dir)
    store = engines.open_oltp(cfg)
    try:
        assert store.execute("select event_id, stream_seq from event") == [
            ("ev-1", 1)
        ]
        assert store.execute("select session_id from session") == [("se-1",)]
        assert store.execute(
            "select scope, key, value, event_id from preference_current"
        ) == [("global", "units", '"usd_m"', "ev-1")]
    finally:
        store.close()

    analytics = engines.open_olap(cfg)
    try:
        assert analytics.execute("select fact_row_id, value from fact") == [
            ("fa-1", 1234.5)
        ]
        rows = analytics.execute(
            "select chunk_id,"
            f" array_cosine_similarity(vector, ?::float[{_DIM}])"
            " from chunk_embedding",
            (_vector(),),
        )
    finally:
        analytics.close()
    assert len(rows) == 1
    chunk_id, similarity = rows[0]
    assert chunk_id == "ch-1"
    assert abs(similarity - 1.0) < 1e-6
