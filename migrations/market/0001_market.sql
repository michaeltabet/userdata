-- Market store (DuckDB). Keyed so a repeat pull replaces, never doubles.

create table companies (
    cik varchar primary key,
    company_name varchar,
    sic_code varchar,
    fiscal_year_end varchar,
    tickers json,
    exchanges json,
    fetched_at timestamp not null
);

create table filings (
    accession_number varchar primary key,
    cik varchar not null,
    form_type varchar not null,
    primary_document varchar,
    filing_items varchar,
    filed_date date,
    report_date date,
    accepted_at timestamp,
    fetched_at timestamp not null
);

create table facts (
    fact_id varchar primary key,
    cik varchar not null,
    accession_number varchar,
    taxonomy_name varchar,
    concept_name varchar not null,
    unit_name varchar,
    fiscal_period varchar,
    form_type varchar,
    fiscal_year integer,
    fact_value double,
    period_start_date date,
    period_end_date date,
    filed_date date,
    fetched_at timestamp not null
);

create table prices (
    ticker varchar not null,
    open_price double,
    high_price double,
    low_price double,
    close_price double,
    adjusted_close_price double,
    dividend_amount double,
    split_ratio double,
    share_volume bigint,
    trade_date date not null,
    fetched_at timestamp not null,
    primary key (ticker, trade_date)
);

create table statement_lines (
    ticker varchar not null,
    statement_name varchar not null,
    timescale varchar not null,
    line_item varchar not null,
    line_value double,
    period_end_date date not null,
    fetched_at timestamp not null,
    primary key (ticker, statement_name, timescale, line_item, period_end_date)
);

create table profiles (
    ticker varchar not null,
    profile json not null,
    fetched_at timestamp not null,
    primary key (ticker, fetched_at)
);
