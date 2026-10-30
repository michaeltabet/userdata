-- USERDATA analytical store, migration 0001: the core derived schema.
--
-- DuckDB now, ClickHouse later (SDD 8.2). Every table here is derived: a
-- pure function of SQLite records, raw payloads and a code version, so it is
-- rebuildable and not backed up. Each table has a natural-key primary key;
-- loads use `insert ... on conflict do nothing`. No triggers.
--
-- The runner splits this file on a `;` that ends a line and replaces
-- {EMBED_DIM} with the configured vector width. Ids named *_row_id are
-- sha256 of the natural key in the comment beside them (ids.row_id).


-- 5.3 Facts ------------------------------------------------------------------

-- derived: one long table for every number, reported, derived or manual.
create table fact (
    -- sha256 of the natural key for its origin (SDD 5.3):
    --   reported/edgar: accession, concept_id, period_start, period_end,
    --     unit, dimensions_key
    --   reported/yahoo: raw_sha256, concept_id, timescale, period_end,
    --     dimensions_key
    --   derived/mt: mapping_taxonomy_version_id, concept_id, issuer_id,
    --     period_start, period_end, unit, dimensions_key, code_version,
    --     sorted input fact_row_ids
    --   manual/mt: manual_fact_id
    fact_row_id varchar primary key,
    origin varchar not null check (
        origin in ('reported', 'derived', 'manual')
    ),
    source varchar not null check (source in ('edgar', 'yahoo', 'mt')),
    issuer_id varchar not null,
    accession varchar,
    concept_id varchar not null,
    concept_version_id varchar,
    period_start date,
    period_end date not null,
    fiscal_period_id varchar,
    timescale varchar check (timescale in ('annual', 'quarterly', 'trailing')),
    unit varchar not null,
    dimensions json,
    dimensions_schema varchar not null,
    dimensions_key varchar not null default '',
    value double,
    decimals varchar,
    statement_basis varchar not null check (
        statement_basis in ('as_reported', 'restated', 'pro_forma', 'carve_out')
    ),
    known_at timestamp not null,
    known_at_precision varchar not null check (
        known_at_precision in ('datetime', 'date')
    ),
    source_fact_id varchar,
    context_ref varchar,
    frame varchar,
    is_audited boolean,
    is_estimated boolean,
    data_quality varchar,
    confidence double,
    raw_sha256 varchar,
    mapping_taxonomy_version_id varchar,
    manual_fact_id varchar,
    code_version varchar not null,
    load_batch_id varchar not null
);

-- derived: the reported facts a derived fact was computed from.
create table fact_input (
    fact_row_id varchar not null,
    input_fact_row_id varchar not null,
    weight double,
    primary key (fact_row_id, input_fact_row_id)
);

-- derived: XBRL footnotes attached to a fact.
create table fact_footnote (
    fact_row_id varchar not null,
    footnote_id varchar not null,
    footnote_text varchar not null,
    raw_sha256 varchar,
    code_version varchar not null,
    primary key (fact_row_id, footnote_id)
);

-- derived: per-filing presentation, calculation and definition arcs.
create table filing_concept_relation (
    accession varchar not null,
    role_uri varchar not null,
    arc_kind varchar not null check (
        arc_kind in ('presentation', 'calculation', 'definition')
    ),
    parent_concept_id varchar not null,
    child_concept_id varchar not null,
    weight double,
    order_no double,
    preferred_label varchar,
    raw_sha256 varchar,
    code_version varchar not null,
    primary key (
        accession,
        role_uri,
        arc_kind,
        parent_concept_id,
        child_concept_id
    )
);

-- derived: how a filing presented its numbers, line by line.
create table statement_line (
    -- sha256(accession, statement, line_no, code_version)
    line_row_id varchar primary key,
    accession varchar not null,
    filed_on date,
    statement varchar not null check (
        statement in (
            'income',
            'balance',
            'cashflow',
            'equity',
            'comprehensive'
        )
    ),
    statement_name varchar,
    line_no integer not null,
    label varchar,
    concept_id varchar,
    preferred_sign integer,
    fact_row_id varchar,
    raw_sha256 varchar,
    code_version varchar not null
);

-- derived: proof that an input was loaded into a table by a code version.
create table load_log (
    load_batch_id varchar primary key,
    input_ref varchar not null,  -- raw_sha256 or event_id
    code_version varchar not null,
    target_table varchar not null,
    row_count bigint not null,
    loaded_at timestamp not null
);


-- 5.5 Chunks and vectors -----------------------------------------------------

-- derived: a text unit of one attachment of a document.
create table chunk (
    -- sha256(attachment_id, chunker_version, ordinal)
    chunk_id varchar primary key,
    attachment_id varchar not null,
    document_id varchar not null,
    issuer_id varchar,
    filed_on date,
    ordinal integer not null,
    section varchar,
    char_start integer not null,
    char_end integer not null,
    text varchar not null,
    n_tokens integer,
    chunker_version varchar not null,
    raw_sha256 varchar
);

-- derived: one embedding of a chunk, with filter columns denormalised in.
create table chunk_embedding (
    chunk_id varchar not null,
    model varchar not null,
    chunker_version varchar not null,
    dim integer not null,
    vector float[{EMBED_DIM}] not null,
    issuer_id varchar,
    document_id varchar not null,
    form varchar,
    filed_on date,
    section varchar,
    created_at timestamp not null,
    primary key (chunk_id, model, chunker_version)
);


-- 5.5 Prices, ratios, screens ------------------------------------------------

-- derived: daily prices per listing, one row per payload that gave them.
-- A revised payload is a new row; price_latest picks the newest.
create table price_daily (
    -- sha256(listing_id, trade_date, source, raw_sha256)
    price_row_id varchar primary key,
    listing_id varchar not null,
    trade_date date not null,
    open double,
    high double,
    low double,
    close double,
    adj_close double,
    volume bigint,
    dividends double,
    stock_splits double,
    capital_gains double,
    repaired boolean,
    source varchar not null,
    known_at timestamp not null,
    known_at_precision varchar not null check (
        known_at_precision in ('datetime', 'date')
    ),
    raw_sha256 varchar not null,
    code_version varchar not null
);

-- derived: a currency rate per pair per day, one row per payload.
-- A revised payload is a new row; fx_rate_latest picks the newest.
create table fx_rate (
    base varchar not null,
    quote varchar not null,
    rate_date date not null,
    rate double not null,
    source varchar not null,
    known_at timestamp not null,
    raw_sha256 varchar not null,
    primary key (base, quote, rate_date, raw_sha256)
);

-- derived: a number computed by a named method at a knowledge cut-off.
create table ratio (
    -- sha256(issuer_id, listing_id, ratio_name, method_version, as_of)
    ratio_row_id varchar primary key,
    issuer_id varchar not null,
    listing_id varchar,
    ratio_name varchar not null,
    method_version varchar not null,  -- ours, or yahoo:<fetched_at>
    as_of date not null,
    price_date date,
    value double,
    run_id varchar,
    code_version varchar not null
);

-- derived: every number a ratio used.
create table ratio_input (
    ratio_row_id varchar not null,
    input_kind varchar not null check (input_kind in ('fact', 'price', 'fx')),
    input_row_id varchar not null,
    role varchar not null check (
        role in ('numerator', 'denominator', 'adjustment')
    ),
    primary key (ratio_row_id, input_kind, input_row_id)
);

-- derived: pass or fail and score per listing per screen version per date.
create table screen_result (
    screen_version_id varchar not null,
    listing_id varchar not null,
    as_of date not null,
    passed boolean not null,
    score double,
    run_id varchar,
    code_version varchar not null,
    primary key (screen_version_id, listing_id, as_of)
);


-- Catalogue additions: ownership and estimates -------------------------------

-- derived: one Form 3/4/5 transaction row.
create table insider_transaction (
    -- sha256(accession, is_derivative, txn_seq)
    txn_row_id varchar primary key,
    accession varchar not null,
    txn_seq integer not null,
    issuer_id varchar not null,
    owner_cik varchar not null,
    owner_name varchar,
    is_director boolean,
    is_officer boolean,
    is_ten_pct_owner boolean,
    officer_title varchar,
    security_title varchar,
    is_derivative boolean not null,
    txn_date date,
    code varchar,
    shares double,
    price double,
    acquired_disposed varchar check (acquired_disposed in ('A', 'D')),
    shares_after double,
    ownership varchar check (ownership in ('direct', 'indirect')),
    nature varchar,
    exercise_price double,
    expiry_date date,
    underlying_title varchar,
    underlying_shares double,
    footnotes json,
    footnotes_schema varchar not null,
    raw_sha256 varchar,
    code_version varchar not null
);

-- derived: an institutional or fund holding as Yahoo reported it.
create table holder_position (
    issuer_id varchar not null,
    holder_kind varchar not null check (
        holder_kind in ('institution', 'fund')
    ),
    holder_name varchar not null,
    report_date date not null,
    shares double,
    value double,
    pct_held double,
    source varchar not null,
    raw_sha256 varchar not null,
    code_version varchar not null,
    primary key (
        issuer_id,
        holder_kind,
        holder_name,
        report_date,
        raw_sha256
    )
);

-- derived: an analyst estimate, target or recommendation as fetched.
create table analyst_estimate (
    issuer_id varchar not null,
    kind varchar not null,  -- earnings_estimate | eps_trend | ...
    period varchar not null,  -- 0q | +1q | 0y | +1y | ...
    metric varchar not null,
    value double,
    n_analysts integer,
    fetched_at timestamp not null,
    raw_sha256 varchar not null,
    code_version varchar not null,
    primary key (issuer_id, kind, period, metric, raw_sha256)
);


-- Views: the latest revision of each revisable row ---------------------------

-- view: newest price per (listing_id, trade_date, source) by known_at.
create view price_latest as
select *
from price_daily
qualify row_number() over (
    partition by listing_id, trade_date, source
    order by known_at desc, raw_sha256 desc
) = 1;

-- view: newest rate per (base, quote, rate_date) by known_at.
create view fx_rate_latest as
select *
from fx_rate
qualify row_number() over (
    partition by base, quote, rate_date
    order by known_at desc, raw_sha256 desc
) = 1;
