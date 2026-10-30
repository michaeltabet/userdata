-- USERDATA transactional store, migration 0001: the core schema.
--
-- SQLite now, Postgres later (SDD 8.1). The runner wraps this file in
-- `begin immediate; ... commit;`, so it holds no transaction or pragma
-- statements.
--
-- Conventions (SDD 5, DATA-CATALOGUE 3):
--   * The line above each `create table` says its kind (sor, projection,
--     reference, derived) and its purpose. scripts/schema_doc.py reads it.
--   * Timestamps are text YYYY-MM-DDTHH:MM:SSZ (UTC); dates are text
--     YYYY-MM-DD. Both are enforced by glob checks.
--   * JSON is text with json_valid(); open documents carry a *_schema
--     column holding name@version (SDD 9.2).
--   * Booleans are integer 0 or 1.
--   * Columns that name a DuckDB row (chunk_id, fact_row_id, ratio_row_id)
--     are cross-store references: deterministic ids, not foreign keys.
--   * Validity intervals are half-open [valid_from, valid_to);
--     '9999-12-31' means open.


-- 5.2 Authored state ---------------------------------------------------------

-- sor: who did something; Michael, Claude, each skill, the scheduler.
create table actor (
    actor_id text primary key,  -- michael | claude | skill:ID | scheduler
    kind text not null check (kind in ('human', 'agent', 'skill', 'scheduler')),
    name text not null
);

-- sor: a research project grouping sessions, theses, lists and runs.
create table project (
    project_id text primary key,  -- uuid7
    name text not null unique,
    goal text,
    status text not null default 'active' check (  -- projection of events
        status in ('active', 'paused', 'closed')
    ),
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    closed_at text check (
        closed_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: content-addressed bytes for skill files and report artifacts.
create table blob (
    sha256 text primary key check (length(sha256) = 64),
    bytes blob not null,
    media_type text not null,
    size integer not null check (size = length(bytes))
);

-- sor: an outside response exactly as received; the file lives under raw/.
create table raw_payload (
    raw_sha256 text primary key check (length(raw_sha256) = 64),
    path text not null,  -- raw/<source>/<sha256 prefix dirs>
    bytes integer not null check (bytes >= 0),
    content_type text not null,
    first_seen_at text not null check (
        first_seen_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: the event log; every authored change, the truth for projections.
create table event (
    event_id text primary key,  -- uuid7 from the client; idempotency key
    stream text not null,  -- preference:global | session:ID | thesis:ID ...
    stream_seq integer not null check (stream_seq >= 1),
    type text not null,  -- preference_set | session_started | ...
    type_version integer not null default 1 check (type_version >= 1),
    payload text not null check (json_valid(payload)),
    payload_schema text not null,  -- name@version
    actor_id text not null references actor (actor_id),
    causation_id text references event (event_id),
    correlation_id text,  -- usually the session_id
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (stream, stream_seq)
);

-- sor: transactional outbox handing events to the DuckDB projector.
create table outbox (
    outbox_id text primary key,
    event_id text not null references event (event_id),
    target text not null default 'duckdb' check (target in ('duckdb')),
    status text not null default 'pending' check (
        status in ('pending', 'done', 'failed')
    ),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    processed_at text check (
        processed_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (event_id, target)
);

-- projection: a working session, rebuilt from session_* events.
create table session (
    session_id text primary key,
    project_id text references project (project_id),
    actor_id text not null references actor (actor_id),
    client text not null check (client in ('claude-code', 'claude-desktop')),
    started_at text not null check (
        started_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    ended_at text check (
        ended_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    title text,
    context text check (json_valid(context)),
    context_schema text not null
);

-- projection: the preference in force per (scope, key); history is in event.
create table preference_current (
    scope text not null,  -- global | skill:ID | issuer:ID
    key text not null,
    value text not null check (json_valid(value)),
    value_schema text not null,
    event_id text not null references event (event_id),
    updated_at text not null check (
        updated_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (scope, key)
);

-- sor: a skill's identity; current_version_id projects skill_published.
create table skill (
    skill_id text primary key,  -- uuid7
    name text not null unique,
    purpose text,
    current_version_id text references skill_version (skill_version_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: one immutable version of a skill; ~/.claude/skills is an export.
create table skill_version (
    skill_version_id text primary key,  -- uuid7
    skill_id text not null references skill (skill_id),
    version integer not null check (version >= 1),
    parent_version_id text references skill_version (skill_version_id),
    manifest_sha256 text not null,  -- over sorted rel_path + blob pairs
    props text not null check (json_valid(props)),
    props_schema text not null,
    created_by text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (skill_id, version)
);

-- sor: the files of a skill version (SKILL.md, references, scripts).
create table skill_version_file (
    skill_version_id text not null
        references skill_version (skill_version_id),
    rel_path text not null,
    blob_sha256 text not null references blob (sha256),
    primary key (skill_version_id, rel_path)
);

-- sor: one execution of a skill version; the lineage anchor.
create table skill_run (
    run_id text primary key,  -- uuid7
    project_id text references project (project_id),
    skill_version_id text not null
        references skill_version (skill_version_id),
    session_id text references session (session_id),
    actor_id text not null references actor (actor_id),
    started_at text not null check (
        started_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    ended_at text check (
        ended_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    status text not null default 'running' check (
        status in ('running', 'ok', 'failed', 'partial')
    ),
    inputs text not null check (json_valid(inputs)),
    inputs_schema text not null,
    as_of_event_id text references event (event_id)
);

-- sor: what a skill run concluded, written once.
create table skill_report (
    run_id text primary key references skill_run (run_id),
    summary text not null,
    body text not null check (json_valid(body)),
    body_schema text not null,
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: an artifact file a skill run produced, stored as a blob.
create table report_file (
    run_id text not null references skill_run (run_id),
    rel_path text not null,
    blob_sha256 text not null references blob (sha256),
    primary key (run_id, rel_path)
);


-- 5.5 Cache ------------------------------------------------------------------

-- sor: every outside call, success or error; many calls share one payload.
create table source_call (
    call_id text primary key,  -- uuid7
    source text not null check (source in ('edgar', 'yahoo', 'figi')),
    endpoint text not null,
    params text not null check (json_valid(params)),  -- canonical form
    params_schema text not null,
    params_sha256 text not null,
    requested_at text not null check (
        requested_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    http_status integer,
    error_class text check (
        error_class in ('rate_limited', 'not_found', 'upstream', 'network')
    ),
    raw_sha256 text references raw_payload (raw_sha256),
    ttl_seconds integer not null check (ttl_seconds >= 0),
    negative_ttl_seconds integer not null check (negative_ttl_seconds >= 0),
    run_id text references skill_run (run_id),
    actor_id text not null references actor (actor_id),
    check (raw_sha256 is not null or error_class is not null)
);


-- 5.1 Identity and reference -------------------------------------------------

-- reference: the legal filer; id is cik:0000000000 when a CIK exists.
create table issuer (
    issuer_id text primary key,  -- cik:0000000000, else uuid7
    name text not null,
    cik text unique check (
        cik glob '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    lei text,
    sic text,
    sic_description text,
    state_of_inc text,
    fye_mmdd text check (fye_mmdd glob '[0-1][0-9][0-3][0-9]'),
    ein text,
    entity_type text,  -- operating | ...
    category text,  -- large accelerated filer | ...
    website text,
    phone text,
    business_address text check (json_valid(business_address)),
    business_address_schema text not null,
    mailing_address text check (json_valid(mailing_address)),
    mailing_address_schema text not null,
    sector text,  -- from the Yahoo profile snapshot
    industry text,
    employees integer check (employees >= 0),
    country text,
    source_call_id text references source_call (call_id),
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- reference: an issuer's names over time (SEC former_names plus current).
create table issuer_name (
    issuer_id text not null references issuer (issuer_id),
    name text not null,
    valid_from text not null check (
        valid_from glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    valid_to text not null default '9999-12-31' check (
        valid_to glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    source_call_id text references source_call (call_id),
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (issuer_id, name, valid_from),
    check (valid_from <= valid_to)
);

-- derived: a Yahoo info document as fetched; keys drift, so kept whole.
create table issuer_profile_snapshot (
    issuer_id text not null references issuer (issuer_id),
    source text not null check (source in ('yahoo')),
    fetched_at text not null check (
        fetched_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    raw_sha256 text not null references raw_payload (raw_sha256),
    payload text not null check (json_valid(payload)),
    payload_schema text not null,  -- yahoo-info@1
    primary key (issuer_id, source, fetched_at)
);

-- reference: a natural person who files Forms 3/4/5, keyed by CIK.
create table person (
    owner_cik text primary key check (
        owner_cik glob '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    name text not null,
    source_call_id text references source_call (call_id),
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- reference: one instrument of an issuer (GOOG and GOOGL are two).
create table security (
    security_id text primary key,  -- uuid7
    issuer_id text not null references issuer (issuer_id),
    kind text not null check (
        kind in ('common', 'preferred', 'when_issued', 'adr', 'unit')
    ),
    class_name text,  -- e.g. Class A
    isin text unique,
    cusip text unique,
    figi_share_class text,
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- reference: one ticker on one exchange over time; prices key on this.
create table listing (
    listing_id text primary key,  -- uuid7
    security_id text not null references security (security_id),
    exchange_mic text not null,  -- XNAS, XNYS
    ticker text not null,
    figi_exchange text,
    when_issued integer not null default 0 check (when_issued in (0, 1)),
    currency text,  -- from yfinance history_metadata
    timezone text,
    first_trade_date text check (
        first_trade_date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    -- SEC gives current tickers only, so valid_from is "first seen by us",
    -- not the exchange's listing date.
    valid_from text not null check (
        valid_from glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    valid_to text not null default '9999-12-31' check (
        valid_to glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    source_call_id text references source_call (call_id),
    check (valid_from < valid_to)
);

-- reference: every external id at its real level, with validity.
create table identifier_assignment (
    assignment_id text primary key,  -- uuid7; one per scheme+value+exchange
    scheme text not null check (
        scheme in ('cik', 'lei', 'isin', 'cusip', 'figi', 'ticker')
    ),
    value text not null,
    level text not null check (level in ('issuer', 'security', 'listing')),
    target_id text not null,  -- issuer_id, security_id or listing_id
    exchange text,  -- exchange MIC; required for tickers
    valid_from text not null check (
        valid_from glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    valid_to text not null default '9999-12-31' check (
        valid_to glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    source_call_id text references source_call (call_id),
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    check (valid_from < valid_to),
    check (scheme <> 'ticker' or exchange is not null)
);

-- sor: two issuers found to be one; lookups follow merged to survivor.
create table entity_alias (
    merged_issuer_id text primary key references issuer (issuer_id),
    survivor_issuer_id text not null references issuer (issuer_id),
    merged_at text not null check (
        merged_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    reason text not null,
    check (merged_issuer_id <> survivor_issuer_id)
);

-- reference: how two companies relate; an edge table walked by CTE.
create table entity_relation (
    relation_id text primary key,  -- uuid7
    from_issuer_id text not null references issuer (issuer_id),
    to_issuer_id text not null references issuer (issuer_id),
    kind text not null check (
        kind in (
            'parent',
            'spun_off_from',
            'predecessor',
            'subsidiary',
            'acquirer'
        )
    ),
    effective_on text check (
        effective_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    source_call_id text references source_call (call_id),
    note text,
    check (from_issuer_id <> to_issuer_id)
);


-- 5.5 Documents --------------------------------------------------------------

-- derived: a filing, news item or user document; kept here for its FKs.
create table document (
    document_id text primary key,  -- accession when EDGAR, else sha256
    issuer_id text references issuer (issuer_id),
    source text not null check (source in ('edgar', 'yahoo', 'user')),
    form text not null,  -- 10-K, 8-K, news, ...
    accession text unique,
    filed_on text check (
        filed_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    report_date text check (
        report_date glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    accepted_at text check (  -- EDGAR acceptance time = known_at
        accepted_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    url text,
    raw_sha256 text not null references raw_payload (raw_sha256),
    title text,
    file_number text,
    film_number text,
    items text check (json_valid(items)),  -- 8-K item codes
    items_schema text not null,
    size integer check (size >= 0),
    primary_document text,
    is_xbrl integer check (is_xbrl in (0, 1)),
    is_inline_xbrl integer check (is_inline_xbrl in (0, 1)),
    act text,
    publisher text,  -- news only
    published_at text check (
        published_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    parser_version text not null
);

-- derived: one file inside a filing (exhibit, XBRL instance, graphic).
create table attachment (
    attachment_id text primary key,  -- sha256(document_id, seq)
    document_id text not null references document (document_id),
    seq integer not null check (seq >= 0),
    filename text not null,
    description text,
    attachment_type text,  -- EX-21, EX-99.1, XML, GRAPHIC, ...
    size integer check (size >= 0),
    raw_sha256 text references raw_payload (raw_sha256),
    unique (document_id, seq)
);

-- reference: splits, dividends, ticker changes, mergers, calendar dates.
create table corporate_action (
    action_id text primary key,  -- uuid7
    issuer_id text not null references issuer (issuer_id),
    security_id text references security (security_id),
    kind text not null check (
        kind in (
            'split',
            'dividend',
            'capital_gain',
            'distribution',
            'ticker_change',
            'merger',
            'earnings_date',
            'ex_dividend'
        )
    ),
    source text not null check (source in ('edgar', 'yahoo', 'user')),
    ratio_num real,
    ratio_den real check (ratio_den <> 0),
    amount real,  -- cash per share for dividends and capital gains
    currency text,
    declared_on text check (
        declared_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    record_on text check (
        record_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    ex_on text check (
        ex_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    effective_on text check (
        effective_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    wi_start text check (  -- when-issued window
        wi_start glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    wi_end text check (
        wi_end glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    form8937_document_id text references document (document_id),
    source_call_id text references source_call (call_id)
);

-- derived: what FY2025 Q2 means for one issuer, from DEI facts.
create table fiscal_period (
    fiscal_period_id text primary key,  -- issuer_id:FY2025:Q2
    issuer_id text not null references issuer (issuer_id),
    fiscal_year integer not null,
    fiscal_period text not null check (
        fiscal_period in ('FY', 'Q1', 'Q2', 'Q3')
    ),
    period_start text not null check (
        period_start glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    period_end text not null check (
        period_end glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    from_accession text,  -- the DEI source filing
    unique (issuer_id, fiscal_year, fiscal_period)
);


-- 5.3 Concepts ---------------------------------------------------------------

-- sor: a namespace; base, vendor, standard, own or one filer's extension.
create table taxonomy (
    taxonomy_id text primary key,  -- us-gaap | dei | yahoo | std | mt | ...
    prefix text not null unique,
    namespace_uri text,  -- year-specific URIs live on taxonomy_version
    kind text not null check (
        kind in ('base', 'vendor', 'standard', 'own', 'company')
    )
);

-- sor: a snapshot of a taxonomy: draft, validated by Arelle, published.
create table taxonomy_version (
    taxonomy_version_id text primary key,  -- uuid7
    taxonomy_id text not null references taxonomy (taxonomy_id),
    version integer not null check (version >= 1),
    version_label text,  -- 2025 | yfinance@0.2.x | edgartools@4.x
    namespace_uri text,
    status text not null default 'draft' check (
        status in ('draft', 'validated', 'published')
    ),
    arelle_report_sha256 text references blob (sha256),
    created_by text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    published_at text check (
        published_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (taxonomy_id, version),
    check ((status = 'published') = (published_at is not null))
);

-- sor: a concept's identity; the id is its qname.
create table concept (
    concept_id text primary key,  -- qname, e.g. mt:AdjustedEbitda
    taxonomy_id text not null references taxonomy (taxonomy_id),
    local_name text not null,
    unique (taxonomy_id, local_name)
);

-- sor: what a concept meant in one taxonomy version; insert-only.
create table concept_version (
    concept_version_id text primary key,  -- uuid7
    concept_id text not null references concept (concept_id),
    taxonomy_version_id text not null
        references taxonomy_version (taxonomy_version_id),
    data_type text not null,  -- XBRL item type, e.g. monetaryItemType
    period_type text not null check (period_type in ('duration', 'instant')),
    balance text not null default 'none' check (
        balance in ('debit', 'credit', 'none')
    ),
    abstract integer not null default 0 check (abstract in (0, 1)),
    definition text,
    labels text check (json_valid(labels)),  -- role -> lang -> text
    labels_schema text not null,
    unique (concept_id, taxonomy_version_id)
);

-- sor: the taxonomy graph, one edge per arc, per taxonomy version.
create table concept_relation (
    taxonomy_version_id text not null
        references taxonomy_version (taxonomy_version_id),
    from_concept_id text not null references concept (concept_id),
    to_concept_id text not null references concept (concept_id),
    arcrole text not null check (
        arcrole in (
            'parent-child',
            'summation-item',
            'dimension-domain',
            'domain-member',
            'hypercube-dimension',
            'dimension-default',
            'all',
            'notAll',
            'general-special',
            'essence-alias'
        )
    ),
    weight real,
    order_no integer,
    primary key (
        taxonomy_version_id,
        from_concept_id,
        to_concept_id,
        arcrole
    )
);

-- sor: the formula as data; one row per input of a target concept.
create table concept_mapping (
    mapping_id text primary key,  -- uuid7
    taxonomy_version_id text not null
        references taxonomy_version (taxonomy_version_id),
    target_concept_id text not null references concept (concept_id),
    input_concept_id text not null references concept (concept_id),
    scope_issuer_id text references issuer (issuer_id),  -- per-issuer rule
    weight real not null default 1,
    sign integer not null default 1 check (sign in (-1, 1)),
    period_rule text not null default 'same' check (
        period_rule in ('same', 'ttm', 'annualise')
    ),
    note text
);

-- sor: a number Michael typed; projected into fact with origin = manual.
create table manual_fact (
    manual_fact_id text primary key,  -- uuid7
    concept_id text not null references concept (concept_id),
    issuer_id text not null references issuer (issuer_id),
    period_start text check (  -- null for instants
        period_start glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    period_end text not null check (
        period_end glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    unit text not null,
    value real not null,
    dimensions text check (json_valid(dimensions)),
    dimensions_schema text not null,
    statement_basis text not null default 'as_reported' check (
        statement_basis in (
            'as_reported',
            'restated',
            'pro_forma',
            'carve_out'
        )
    ),
    basis_note text not null,  -- where the number came from, in words
    event_id text not null references event (event_id),
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);


-- 5.4 Tags, theses, research, evidence ---------------------------------------

-- sor: an own label; namespace separates Michael's from a skill's.
create table tag (
    tag_id text primary key,  -- uuid7
    namespace text not null check (
        namespace = 'mt' or namespace glob 'skill:?*'
    ),
    name text not null,
    description text,
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (namespace, name)
);

-- sor: a tag applied to a document.
create table document_tag (
    tag_id text not null references tag (tag_id),
    document_id text not null references document (document_id),
    run_id text references skill_run (run_id),
    note text,
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (tag_id, document_id)
);

-- sor: a tag applied to a DuckDB chunk (cross-store id).
create table chunk_tag (
    tag_id text not null references tag (tag_id),
    chunk_id text not null,  -- xstore: DuckDB chunk
    run_id text references skill_run (run_id),
    note text,
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (tag_id, chunk_id)
);

-- sor: a tag applied to a DuckDB fact (cross-store id).
create table fact_tag (
    tag_id text not null references tag (tag_id),
    fact_row_id text not null,  -- xstore: DuckDB fact
    run_id text references skill_run (run_id),
    note text,
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (tag_id, fact_row_id)
);

-- sor: one investment idea about an issuer or a pair of related issuers.
create table thesis (
    thesis_id text primary key,  -- uuid7
    project_id text references project (project_id),
    subject_issuer_id text references issuer (issuer_id),
    subject_relation_id text references entity_relation (relation_id),
    stance text not null check (stance in ('long', 'short', 'watch', 'avoid')),
    status text not null default 'draft' check (
        status in ('draft', 'active', 'closed', 'invalidated')
    ),
    current_version_id text references thesis_version (thesis_version_id),
    opened_on text not null check (
        opened_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    closed_on text check (
        closed_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    actor_id text not null references actor (actor_id)
);

-- sor: the thesis text at one point in time; insert-only.
create table thesis_version (
    thesis_version_id text primary key,  -- uuid7
    thesis_id text not null references thesis (thesis_id),
    version integer not null check (version >= 1),
    body text not null,
    created_by text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (thesis_id, version)
);

-- sor: one testable statement of a thesis with its kill criterion.
create table thesis_claim (
    claim_id text primary key,  -- uuid7
    thesis_id text not null references thesis (thesis_id),
    kind text not null check (
        kind in ('catalyst', 'valuation', 'risk', 'structure')
    ),
    statement text not null,
    kill_criterion text not null,
    status text not null default 'open' check (
        status in ('open', 'supported', 'refuted')
    ),
    opened_on text not null check (
        opened_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    resolved_on text check (
        resolved_on glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    )
);

-- sor: the unit of research work; a queue Claude picks from.
create table research_question (
    question_id text primary key,  -- uuid7
    project_id text references project (project_id),
    thesis_id text references thesis (thesis_id),
    claim_id text references thesis_claim (claim_id),
    question text not null,
    priority integer not null default 0,
    status text not null default 'open' check (
        status in ('open', 'in_progress', 'answered', 'dropped')
    ),
    assignee_actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: one step taken for a question; append-only trail.
create table research_step (
    step_id text primary key,  -- uuid7
    question_id text not null references research_question (question_id),
    seq integer not null check (seq >= 1),
    actor_id text not null references actor (actor_id),
    run_id text references skill_run (run_id),
    call_id text references source_call (call_id),
    finding text not null,
    next_step text,
    recorded_at text not null check (
        recorded_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (question_id, seq)
);

-- sor: the answer that closes a question, 1:1.
create table research_answer (
    question_id text primary key references research_question (question_id),
    answer text not null,
    answered_by text not null references actor (actor_id),
    answered_at text not null check (
        answered_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    event_id text not null references event (event_id)
);

-- sor: one link from a claim to exactly one source (exclusive arc).
create table evidence (
    evidence_id text primary key,  -- uuid7
    claim_id text not null references thesis_claim (claim_id),
    role text not null check (role in ('supports', 'contradicts', 'context')),
    note text,
    chunk_id text,  -- xstore: DuckDB chunk
    fact_row_id text,  -- xstore: DuckDB fact
    ratio_row_id text,  -- xstore: DuckDB ratio
    document_id text references document (document_id),
    answer_question_id text references research_answer (question_id),
    created_by text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    check (
        (chunk_id is not null)
        + (fact_row_id is not null)
        + (ratio_row_id is not null)
        + (document_id is not null)
        = 1
    )
);


-- 5.5 Screens ----------------------------------------------------------------

-- sor: a screen's identity; current_version_id is a projection.
create table screen (
    screen_id text primary key,  -- uuid7
    project_id text references project (project_id),
    name text not null unique,
    current_version_id text references screen_version (screen_version_id)
);

-- sor: one version of a screen's rules.
create table screen_version (
    screen_version_id text primary key,  -- uuid7
    screen_id text not null references screen (screen_id),
    version integer not null check (version >= 1),
    rules text not null check (json_valid(rules)),
    rules_schema text not null,
    created_by text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    unique (screen_id, version)
);


-- 5.6 The research account ---------------------------------------------------

-- sor: a named list of issuers Michael follows.
create table watchlist (
    watchlist_id text primary key,  -- uuid7
    project_id text references project (project_id),
    name text not null unique,
    purpose text,
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    archived_at text check (
        archived_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: an issuer on a watchlist; a drop sets removed_at, never deletes.
create table watchlist_item (
    watchlist_id text not null references watchlist (watchlist_id),
    issuer_id text not null references issuer (issuer_id),
    added_at text not null check (
        added_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    removed_at text check (
        removed_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    reason text,
    run_id text references skill_run (run_id),  -- the run that added it
    primary key (watchlist_id, issuer_id, added_at),
    check (removed_at >= added_at)
);

-- sor: who a company is compared against.
create table peer_group (
    peer_group_id text primary key,  -- uuid7
    project_id text references project (project_id),
    name text not null unique,
    anchor_issuer_id text references issuer (issuer_id),
    basis text not null check (basis in ('manual', 'sic', 'screen', 'skill')),
    screen_version_id text references screen_version (screen_version_id),
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: one member of a peer group; a drop sets removed_at, never deletes.
create table peer_group_member (
    peer_group_id text not null references peer_group (peer_group_id),
    issuer_id text not null references issuer (issuer_id),
    weight real,
    reason text,
    added_at text not null check (
        added_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    removed_at text check (
        removed_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    ),
    primary key (peer_group_id, issuer_id, added_at),
    check (removed_at >= added_at)
);

-- sor: a search Michael wants to rerun.
create table saved_search (
    saved_search_id text primary key,  -- uuid7
    project_id text references project (project_id),
    name text not null unique,
    kind text not null check (
        kind in ('semantic', 'filing', 'company', 'market', 'screen')
    ),
    params text not null check (json_valid(params)),
    params_schema text not null,
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- projection: every search performed, from search_performed events.
create table search_history (
    search_id text primary key,  -- uuid7
    session_id text references session (session_id),
    actor_id text not null references actor (actor_id),
    kind text not null check (
        kind in ('semantic', 'filing', 'company', 'market', 'screen')
    ),
    query text not null,
    params text not null check (json_valid(params)),
    params_schema text not null,
    result_count integer check (result_count >= 0),
    top_result_ids text check (json_valid(top_result_ids)),
    top_result_ids_schema text not null,
    saved_search_id text references saved_search (saved_search_id),
    searched_at text not null check (
        searched_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: what Michael wrote about a company; an edit is a new note.
create table company_note (
    note_id text primary key,  -- uuid7
    project_id text references project (project_id),
    issuer_id text not null references issuer (issuer_id),
    body text not null,
    pinned integer not null default 0 check (pinned in (0, 1)),
    supersedes_note_id text references company_note (note_id),
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);

-- sor: a saved side-by-side, recomputed from its knowledge cut-off.
create table comparison (
    comparison_id text primary key,  -- uuid7
    project_id text references project (project_id),
    name text not null,
    peer_group_id text references peer_group (peer_group_id),
    params text not null check (json_valid(params)),
    params_schema text not null,
    as_of text not null check (
        as_of glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    run_id text references skill_run (run_id),
    actor_id text not null references actor (actor_id),
    created_at text not null check (
        created_at glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            || 'T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
    )
);


-- Indexes for the access patterns in the SDD rationale tables ----------------

create index session_project on session (project_id);
create index thesis_project on thesis (project_id);
create index watchlist_project on watchlist (project_id);
create index peer_group_project on peer_group (project_id);
create index research_question_project on research_question (project_id);
create index skill_run_project on skill_run (project_id);
create index comparison_project on comparison (project_id);
create index company_note_project on company_note (project_id);
create index saved_search_project on saved_search (project_id);
create index screen_project on screen (project_id);
create index outbox_status_created_at on outbox (status, created_at);
create index session_started_at on session (started_at);
create index skill_version_parent on skill_version (parent_version_id);
create index skill_run_skill_version on skill_run (skill_version_id);
create index skill_run_session on skill_run (session_id);
create index source_call_params on source_call (params_sha256, requested_at);
create index source_call_raw on source_call (raw_sha256);
create index issuer_name_name on issuer_name (name);
create index security_issuer on security (issuer_id);
create index listing_ticker on listing (ticker, exchange_mic, valid_from);
create index listing_security on listing (security_id);
create index identifier_assignment_scheme_value
on identifier_assignment (scheme, value, exchange);
create index identifier_assignment_target
on identifier_assignment (level, target_id);
create index entity_relation_from on entity_relation (from_issuer_id);
create index entity_relation_to on entity_relation (to_issuer_id);
create index document_issuer_form on document (issuer_id, form, filed_on);
create index corporate_action_issuer
on corporate_action (issuer_id, effective_on);
create index concept_version_taxonomy_version
on concept_version (taxonomy_version_id);
create index concept_relation_to
on concept_relation (taxonomy_version_id, to_concept_id);
create index concept_mapping_target
on concept_mapping (taxonomy_version_id, target_concept_id);
create index concept_mapping_input on concept_mapping (input_concept_id);
create index manual_fact_concept_issuer
on manual_fact (concept_id, issuer_id, period_end);
create index document_tag_document on document_tag (document_id);
create index chunk_tag_chunk on chunk_tag (chunk_id);
create index fact_tag_fact on fact_tag (fact_row_id);
create index thesis_subject on thesis (subject_issuer_id);
create index thesis_claim_thesis on thesis_claim (thesis_id, status);
create index evidence_claim on evidence (claim_id);
create index evidence_fact on evidence (fact_row_id);
create index evidence_chunk on evidence (chunk_id);
create index evidence_ratio on evidence (ratio_row_id);
create index evidence_document on evidence (document_id);
create index research_question_status
on research_question (status, priority);
create index research_question_thesis on research_question (thesis_id);
create index watchlist_item_issuer on watchlist_item (issuer_id);
create index peer_group_member_issuer on peer_group_member (issuer_id);
create index search_history_searched_at on search_history (searched_at);
create index search_history_session on search_history (session_id);
create index company_note_issuer on company_note (issuer_id, created_at);


-- Immutability: insert-only tables raise on update and delete (SDD 7) --------

create trigger event_no_update
before update on event
begin
    select raise(abort, 'event is immutable');
end;

create trigger event_no_delete
before delete on event
begin
    select raise(abort, 'event is immutable');
end;

create trigger skill_version_no_update
before update on skill_version
begin
    select raise(abort, 'skill_version is immutable');
end;

create trigger skill_version_no_delete
before delete on skill_version
begin
    select raise(abort, 'skill_version is immutable');
end;

create trigger thesis_version_no_update
before update on thesis_version
begin
    select raise(abort, 'thesis_version is immutable');
end;

create trigger thesis_version_no_delete
before delete on thesis_version
begin
    select raise(abort, 'thesis_version is immutable');
end;

create trigger concept_version_no_update
before update on concept_version
begin
    select raise(abort, 'concept_version is immutable');
end;

create trigger concept_version_no_delete
before delete on concept_version
begin
    select raise(abort, 'concept_version is immutable');
end;

create trigger research_step_no_update
before update on research_step
begin
    select raise(abort, 'research_step is immutable');
end;

create trigger research_step_no_delete
before delete on research_step
begin
    select raise(abort, 'research_step is immutable');
end;

create trigger raw_payload_no_update
before update on raw_payload
begin
    select raise(abort, 'raw_payload is immutable');
end;

create trigger raw_payload_no_delete
before delete on raw_payload
begin
    select raise(abort, 'raw_payload is immutable');
end;

create trigger blob_no_update
before update on blob
begin
    select raise(abort, 'blob is immutable');
end;

create trigger blob_no_delete
before delete on blob
begin
    select raise(abort, 'blob is immutable');
end;

create trigger manual_fact_no_update
before update on manual_fact
begin
    select raise(abort, 'manual_fact is immutable');
end;

create trigger manual_fact_no_delete
before delete on manual_fact
begin
    select raise(abort, 'manual_fact is immutable');
end;


create trigger screen_version_no_update
before update on screen_version
begin
    select raise(abort, 'screen_version is immutable');
end;

create trigger screen_version_no_delete
before delete on screen_version
begin
    select raise(abort, 'screen_version is immutable');
end;

create trigger company_note_no_update
before update on company_note
begin
    select raise(abort, 'company_note is immutable');
end;

create trigger company_note_no_delete
before delete on company_note
begin
    select raise(abort, 'company_note is immutable');
end;

create trigger concept_relation_no_update
before update on concept_relation
begin
    select raise(abort, 'concept_relation is immutable');
end;

create trigger concept_relation_no_delete
before delete on concept_relation
begin
    select raise(abort, 'concept_relation is immutable');
end;

-- Identifiers: one target per (scheme, value, exchange) at a time (SDD 7) ----
-- Exchange is null for every scheme but ticker; `is` compares nulls equal.
-- Intervals are half-open, so [a, b) and [b, c) do not overlap.

create trigger identifier_assignment_no_overlap_insert
before insert on identifier_assignment
when exists (
    select 1
    from identifier_assignment as existing
    where
        existing.scheme = new.scheme
        and existing.value = new.value
        and existing.exchange is new.exchange
        and existing.valid_from < new.valid_to
        and new.valid_from < existing.valid_to
)
begin
    select raise(abort, 'identifier_assignment overlaps');
end;

create trigger identifier_assignment_no_overlap_update
before update on identifier_assignment
when exists (
    select 1
    from identifier_assignment as existing
    where
        existing.assignment_id <> new.assignment_id
        and existing.scheme = new.scheme
        and existing.value = new.value
        and existing.exchange is new.exchange
        and existing.valid_from < new.valid_to
        and new.valid_from < existing.valid_to
)
begin
    select raise(abort, 'identifier_assignment overlaps');
end;


-- Taxonomies: a published version is frozen (SDD 7, REVIEW-1 finding 10) ----

create trigger concept_version_unpublished_only
before insert on concept_version
when (
    select taxonomy_version.status
    from taxonomy_version
    where taxonomy_version.taxonomy_version_id = new.taxonomy_version_id
) = 'published'
begin
    select raise(abort, 'taxonomy_version is published; add a new version');
end;

create trigger concept_mapping_unpublished_only
before insert on concept_mapping
when (
    select taxonomy_version.status
    from taxonomy_version
    where taxonomy_version.taxonomy_version_id = new.taxonomy_version_id
) = 'published'
begin
    select raise(abort, 'taxonomy_version is published; add a new version');
end;


-- Seed rows ------------------------------------------------------------------

insert into actor (actor_id, kind, name)
values
    ('michael', 'human', 'Michael'),
    ('claude', 'agent', 'Claude'),
    ('scheduler', 'scheduler', 'Scheduler');

insert into taxonomy (taxonomy_id, prefix, namespace_uri, kind)
values
    ('us-gaap', 'us-gaap', null, 'base'),
    ('dei', 'dei', null, 'base'),
    ('yahoo', 'yahoo', null, 'vendor'),
    ('std', 'std', null, 'standard'),
    ('mt', 'mt', null, 'own');
