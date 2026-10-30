"""Both stores migrate once, idempotently, to the full SDD schema."""

import re

from userdata import config
from userdata import engines

_OLTP_TABLES = frozenset(
    {
        # 5.1 identity and reference, plus catalogue additions
        "issuer",
        "issuer_name",
        "issuer_profile_snapshot",
        "person",
        "security",
        "listing",
        "identifier_assignment",
        "entity_alias",
        "entity_relation",
        "corporate_action",
        "fiscal_period",
        # 5.2 authored state
        "actor",
        "project",
        "event",
        "outbox",
        "session",
        "preference_current",
        "skill",
        "skill_version",
        "blob",
        "skill_version_file",
        "skill_run",
        "skill_report",
        "report_file",
        # 5.3 concepts
        "taxonomy",
        "taxonomy_version",
        "concept",
        "concept_version",
        "concept_relation",
        "concept_mapping",
        "manual_fact",
        # 5.4 tags, theses, research, evidence
        "tag",
        "document_tag",
        "chunk_tag",
        "fact_tag",
        "thesis",
        "thesis_version",
        "thesis_claim",
        "evidence",
        "research_question",
        "research_step",
        "research_answer",
        # 5.5 cache, documents, screens
        "source_call",
        "raw_payload",
        "document",
        "attachment",
        "screen",
        "screen_version",
        # 5.6 research account
        "watchlist",
        "watchlist_item",
        "peer_group",
        "peer_group_member",
        "search_history",
        "saved_search",
        "company_note",
        "comparison",
        # runner bookkeeping
        "schema_migration",
    }
)

_OLAP_TABLES = frozenset(
    {
        "fact",
        "fact_input",
        "fact_footnote",
        "filing_concept_relation",
        "statement_line",
        "load_log",
        "chunk",
        "chunk_embedding",
        "price_daily",
        "fx_rate",
        "ratio",
        "ratio_input",
        "screen_result",
        "insider_transaction",
        "holder_position",
        "analyst_estimate",
        "schema_migration",
    }
)

_OLAP_VIEWS = frozenset({"price_latest", "fx_rate_latest"})


def test_oltp_migrates_once(cfg: config.Config) -> None:
    """Applies 0001 once; a second call and a new engine apply nothing."""
    engine = engines.open_oltp(cfg)
    try:
        assert engine.migrate() == ["0001_core"]
        assert engine.migrate() == []
    finally:
        engine.close()
    engine = engines.open_oltp(cfg)
    try:
        assert engine.migrate() == []
    finally:
        engine.close()


def test_olap_migrates_once(cfg: config.Config) -> None:
    """Applies 0001 once; a second call and a new engine apply nothing."""
    engine = engines.open_olap(cfg)
    try:
        assert engine.migrate() == ["0001_core"]
        assert engine.migrate() == []
    finally:
        engine.close()
    engine = engines.open_olap(cfg)
    try:
        assert engine.migrate() == []
    finally:
        engine.close()


def test_oltp_has_every_table(cfg: config.Config) -> None:
    """The SQLite store holds exactly the SDD tables."""
    engine = engines.open_oltp(cfg)
    try:
        engine.migrate()
        rows = engine.execute(
            "select name from sqlite_master where type = 'table'"
        )
    finally:
        engine.close()
    assert {row[0] for row in rows} == _OLTP_TABLES


def test_olap_has_every_table(cfg: config.Config) -> None:
    """The DuckDB store holds exactly the SDD tables."""
    engine = engines.open_olap(cfg)
    try:
        engine.migrate()
        rows = engine.execute(
            "select table_name, table_type from information_schema.tables"
            " where table_schema = 'main'"
        )
    finally:
        engine.close()
    tables = {name for name, kind in rows if kind == "BASE TABLE"}
    views = {name for name, kind in rows if kind == "VIEW"}
    assert tables == _OLAP_TABLES
    assert views == _OLAP_VIEWS


def test_oltp_seed_rows(cfg: config.Config) -> None:
    """Actors and taxonomies are seeded with their kinds."""
    engine = engines.open_oltp(cfg)
    try:
        engine.migrate()
        actors = set(engine.execute("select actor_id, kind from actor"))
        taxonomies = set(
            engine.execute("select taxonomy_id, kind from taxonomy")
        )
    finally:
        engine.close()
    assert actors == {
        ("michael", "human"),
        ("claude", "agent"),
        ("scheduler", "scheduler"),
    }
    assert taxonomies == {
        ("us-gaap", "base"),
        ("dei", "base"),
        ("yahoo", "vendor"),
        ("std", "standard"),
        ("mt", "own"),
    }


_PROJECT_SCOPED = (
    "session",
    "thesis",
    "watchlist",
    "peer_group",
    "research_question",
    "skill_run",
    "comparison",
    "company_note",
    "saved_search",
    "screen",
)


def test_project_scoped_tables_reference_project(cfg: config.Config) -> None:
    """Each project-scoped table has a nullable FK to project."""
    engine = engines.open_oltp(cfg)
    try:
        engine.migrate()
        for table in _PROJECT_SCOPED:
            columns = {
                row[1]: row[3]
                for row in engine.execute(f"pragma table_info({table})")
            }
            assert columns.get("project_id") == 0, table
            fks = engine.execute(f"pragma foreign_key_list({table})")
            assert ("project", "project_id") in {
                (fk[2], fk[3]) for fk in fks
            }, table
    finally:
        engine.close()


def test_oltp_json_columns_have_schema(cfg: config.Config) -> None:
    """Every SQLite JSON column has a not-null <col>_schema (SDD 9.2)."""
    engine = engines.open_oltp(cfg)
    try:
        engine.migrate()
        found = 0
        for name, sql in engine.execute(
            "select name, sql from sqlite_master where type = 'table'"
        ):
            columns = {
                row[1]: row[3]
                for row in engine.execute(f"pragma table_info({name})")
            }
            for column in re.findall(r"json_valid\((\w+)\)", sql):
                found += 1
                assert columns.get(f"{column}_schema") == 1, (name, column)
    finally:
        engine.close()
    assert found == 18


def test_olap_json_columns_have_schema(cfg: config.Config) -> None:
    """Every DuckDB JSON column has a not-null <col>_schema (SDD 9.2)."""
    engine = engines.open_olap(cfg)
    try:
        engine.migrate()
        rows = engine.execute(
            "select table_name, column_name, data_type, is_nullable"
            " from information_schema.columns c"
            " join information_schema.tables t using (table_name)"
            " where t.table_type = 'BASE TABLE'"
        )
    finally:
        engine.close()
    nullable = {(t, c): n for t, c, _, n in rows}
    json_columns = [(t, c) for t, c, d, _ in rows if d == "JSON"]
    assert len(json_columns) == 2
    for table, column in json_columns:
        assert nullable.get((table, f"{column}_schema")) == "NO", column
