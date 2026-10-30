# Data catalogue — what the two sources actually return, and where it lands

2026-10-30. Read from the forks' code and docs, no network. Sources:
`~/Slop/mcp-sources/edgartools` (MIT) and `~/Slop/mcp-sources/yfinance` (Apache-2.0).
File paths below are inside those repos.

The point: USERDATA is built **over** these libraries. Their output shapes are the
ground floor of the data model. Where the SDD disagreed with them, the SDD changes.

---

## 1. edgartools

### 1.1 XBRL facts from one filing — `XBRL.facts.to_dataframe()`

Declared columns, `edgar/xbrl/facts.py` lines 51–97. One row per fact, or one row
per fact × dimension when dimensions are exploded.

| Column | Type | Meaning | Lands in |
|---|---|---|---|
| `concept` | str | qname, e.g. `us-gaap:Revenues` | `fact.concept_id` |
| `label` | str | label from the filing's label linkbase | `concept_version.labels` (per filing it is presentation, not identity) |
| `balance` | str | debit / credit | `concept_version.balance` |
| `preferred_sign` | Int64 | sign hint from presentation | `statement_line` |
| `weight` | float | calculation weight | `concept_relation.weight` |
| `value` | str | raw string as filed | kept in `raw/`; not a column |
| `numeric_value` | float | parsed number | `fact.value` |
| `period_key` | str | edgartools' canonical period string | derive, do not store |
| `period_start` | str | ISO date or null | `fact.period_start` |
| `period_end` | str | ISO date | `fact.period_end` |
| `period_instant` | str | ISO date for instants | `fact.period_end` with `period_start` null |
| `period_type` | str | instant / duration | implied by `period_start` null |
| `is_dimensioned` | bool | has any dimension | implied by `dimensions_key` non-empty |
| `decimals` | str | "-6", "INF" | `fact.decimals` as text, not int |
| `statement_type` | str | BalanceSheet, IncomeStatement, ... | `statement_line.statement` |
| `statement_name` | str | the role definition | `statement_line` |
| `fact_id` | str | the `id` attribute in the XML | keep as `fact.source_fact_id` |
| `context_ref` | str | context id in the instance | keep as `fact.context_ref` |
| `unit_ref` | str | unit id in the instance | `fact.unit` after resolving |
| `currency` | str | ISO currency from the unit | `fact.unit` is the currency when monetary |
| `entity_identifier` | str | the CIK in the context | `fact.issuer_id` after mapping |
| `entity_scheme` | str | `http://www.sec.gov/CIK` | no column, always CIK for EDGAR |
| `fiscal_period` | str | FY, Q1, Q2, Q3 | `fiscal_period.fiscal_period` |
| `fiscal_year` | Int64 | | `fiscal_period.fiscal_year` |
| `dimension` | str | axis qname, one row per axis | `fact.dimensions` JSON and `dimensions_key` |
| `member` | str | member qname | same |
| `dimension_label`, `dimension_member_label`, `full_dimension_label` | str | labels | not stored, derivable from concept labels |

Underlying models, `edgar/xbrl/models.py`: `Fact(element_id, context_ref, value,
unit_ref, decimals, numeric_value, footnotes[], instance_id, fact_id)`,
`Context(context_id, entity{}, period{}, dimensions{})`, plus `Footnote`,
`PresentationNode`, `PresentationTree`, `CalculationNode`, `CalculationArc`,
`CalculationTree`, `Axis`, `Domain`, `Table`.

**Model changes this forces**

1. `decimals` is **text**, not int. "INF" is a legal value.
2. Add `fact.source_fact_id` and `fact.context_ref`. They are the only way back to the
   exact XML fact for citation and for Arelle round-trips.
3. Footnotes exist: add `fact_footnote(fact_row_id, footnote_id, text)` in DuckDB.
4. edgartools gives presentation, calculation and definition **trees per filing**,
   not just the base taxonomy. The SDD's `concept_relation` keyed by taxonomy version
   only covers base taxonomies and `mt`. Company extension concepts (`abc:SomeThing`)
   and per-filing calculation arcs need a home: `filing_concept_relation(accession,
   role_uri, arc_kind presentation|calculation|definition, parent, child, weight,
   order, preferred_label)` in DuckDB, derived, keyed by accession.
5. Company-specific concepts are a taxonomy per filer: `taxonomy.kind` gets a value
   `company`, one row per filer prefix, concepts loaded from the filings.

### 1.2 Company facts across filings — `EntityFacts.to_dataframe()`

Declared columns, `edgar/entity/dataframe_schema.py`. This is SEC's
`companyfacts` API parsed, so it is cross-filing and carries point-in-time data.

| Column | Type | Lands in |
|---|---|---|
| `concept`, `label` | str | `fact.concept_id`; label → concept version |
| `value`, `numeric_value` | float | `fact.value` |
| `unit` | str | `fact.unit` |
| `scale` | object | not stored; already applied |
| `period_start`, `period_end`, `period_type` | | as above |
| `fiscal_year` Int64, `fiscal_period` str | | `fiscal_period` |
| `filing_date` | date | `document.filed_on`; **`fact.known_at`** proxy when acceptance time is unknown |
| `form_type` | str | `document.form` |
| `accession` | str | `fact.accession` |
| `taxonomy` | str | `us-gaap`, `dei`, `ifrs-full`, company prefix | `taxonomy_id` |
| `statement_type` | str | `statement_line.statement` |
| `data_quality`, `confidence_score`, `is_audited`, `is_estimated` | str, float, bool, bool | **new**: `fact.quality` JSON or four columns |

Source fields of the SEC API as parsed in `edgar/entity/parser.py`: `units`, `val`,
`start`, `end`, `filed`, `fy`, `fp`, `form`, `accn`, `frame`.

**Model changes**

6. Add `fact.frame` (SEC's `CY2024Q3I` calendar frame) — it is SEC's own
   deduplication key across filings and free to keep.
7. Add quality columns: `is_audited`, `is_estimated`, `data_quality`, `confidence`.
   The SDD's risk register wanted a `dq_issue` table; edgartools already scores rows.
8. `known_at` has two sources: `acceptanceDateTime` from the submissions index (exact)
   and `filed` from companyfacts (date only). Store `known_at` as timestamp and
   `known_at_precision = datetime | date`.

### 1.3 Filings index — `Company.get_filings()` / `EntityFilings`

Fields read from SEC submissions JSON, `edgar/entity/filings.py` lines 217–226:
`accession_number`, `form`, `filing_date`, `reportDate`, `acceptanceDateTime`,
`fileNumber`, `filmNumber`, `items` (8-K item codes), `size`, `primaryDocument`,
`primaryDocDescription`, `isXBRL`, `isInlineXBRL`, `act`.

`Filing` object, `edgar/_filings.py` line 1421: `cik, company, form, filing_date,
accession_no`, plus lazy homepage, SGML, attachments and related entities.

**Model changes**

9. `document` gains: `report_date` (the period the filing is about — different from
   `filed_on`), `file_number`, `film_number`, `items` JSON (8-K items are how you
   find spin and M&A events), `size`, `primary_document`, `is_xbrl`,
   `is_inline_xbrl`, `act`.
10. A filing has many **attachments** (exhibits, the XBRL instance, graphics). The
    SDD's `document` is really the filing; add `attachment(document_id, seq,
    filename, description, type, size, raw_sha256)` in SQLite, derived. Chunks point
    at an attachment, not a filing.

### 1.4 Company — `Company` / `EntityData`

`edgar/entity/data.py` line 299: `cik, name, tickers[], exchanges[], sic,
sic_description, ein, entity_type, fiscal_year_end, filings, business_address,
mailing_address, state_of_incorporation`, plus `former_names`, `category`,
`website`, `investor_website`, `phone`, `flags`, `insider_transaction_for_owner_exists`,
`insider_transaction_for_issuer_exists` from the same submissions JSON.
`Address(street1, street2, city, state_or_country, zipcode, state_or_country_desc)`.

**Model changes**

11. `issuer` gains `sic_description`, `ein`, `entity_type` (operating / ...),
    `category` (large accelerated filer...), `website`, `phone`, and two address
    JSON columns. `former_names` is history: `issuer_name(issuer_id, name,
    valid_from, valid_to)`.
12. SEC gives `tickers[]` and `exchanges[]` as parallel lists, **current only, no
    history**. So `listing.valid_from` is "first seen by us", not an exchange date.
    Write that down; it is the honest meaning. OpenFIGI does not fix this either.

### 1.5 Ticker ↔ CIK — `edgar/reference/tickers.py`

Ships `company_tickers.parquet` and reads SEC `company_tickers.json`
(`cik_str, ticker, title`, 10 430 rows) and `company_tickers_exchange.json`
(`cik, name, ticker, exchange`), plus `cusip_ticker_mapping`. CIK is issuer-level,
ticker + exchange is listing-level. **No FIGI, no ISIN.**

This is enough for v1. OpenFIGI is dropped from v1 scope (lowest priority, Michael
2026-10-30). The `identifier_assignment.scheme` enum keeps `figi` so it can be added
later without a migration.

### 1.6 Insider ownership — Form 3/4/5, `edgar/ownership/models.py`

`Issuer(cik, name, ticker)`, `ReportingRelationship(is_director, is_officer,
is_other, is_ten_pct_owner, officer_title)`, `TransactionCode(form, code,
equity_swap_involved, footnote)`, `PostTransactionAmounts(shares_owned)`,
`Underlying(underlying_security_title, number_of_shares)`, `OwnerSignature`,
`Footnotes`. Transaction tables carry security title, date, code, shares, price,
acquired/disposed, remaining, direct/indirect ownership, nature of ownership, and
for derivatives exercise price, expiry, underlying.

**Model changes**

13. The SDD has no insider table. Add in DuckDB, derived:
    `insider_transaction(txn_row_id, accession, issuer_id, owner_cik, owner_name,
    is_director, is_officer, is_ten_pct_owner, officer_title, security_title,
    is_derivative, txn_date, code, shares, price, acquired_disposed,
    shares_after, ownership direct|indirect, nature, exercise_price,
    expiry_date, underlying_title, underlying_shares, footnotes JSON, raw_sha256,
    code_version)`. Owners are people: `person(owner_cik, name)` in SQLite.

### 1.7 edgartools' own MCP tools — `edgar/ai/mcp/tools/`

Tools: `edgar_company, edgar_search, edgar_screen, edgar_text_search, edgar_monitor,
edgar_filing, edgar_read, edgar_notes, edgar_trends, edgar_compare, edgar_ownership,
edgar_fund, edgar_proxy`. Return JSON with keys like `company, cik, ticker,
identifier, financials{revenue, net_income, gross_profit, operating_income, equity,
liabilities, periods, current, prior, growth}, filings[], accession_number,
filing_date, analysis, risk_factors, mda, controls, legal, full_text, holdings,
total_comp, error{error_code, message, suggestions}`.

These are **summaries for an LLM**, not data. USERDATA calls the library, not these
tools, and stores the library's dataframes. The tool outputs are a good model for
USERDATA's *read* tools (what Claude wants to see), not for storage.

### 1.8 Standardisation — `edgar/xbrl/standardization/`

Maps company concepts to a standard label set (e.g. many revenue concepts →
"Revenue"). Versioned by edgartools release. This is the `std` taxonomy in the SDD,
and the mapping is a `concept_mapping` with `taxonomy_version = edgartools@<ver>`.
Keep edgartools' version string on every derived row (`code_version` already does).

### 1.9 Licence note

`unidecode` (GPL-2.0+) is imported in `edgar/search/datasearch.py` and
`edgar/bdc/search.py` only. Swap for `anyascii` (ISC) in the fork.

---

## 2. yfinance

### 2.1 Prices — `Ticker.history()`

Columns: `Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits,
Capital Gains` (`yfinance/scrapers/history.py`), indexed by timestamp in the
exchange's timezone. Intervals 1m…3mo; intraday limited to the last 60 days.
yfinance repairs bad rows (`repair=True`) and marks them.

**Model changes**

14. `price_daily` gains `dividends`, `stock_splits` (ratio), `capital_gains`,
    `repaired bool`, and `interval` so intraday rows can share the table later or
    get `price_bar` with the same columns plus `ts`. v1: daily only.
15. `history_metadata` returns `currency, exchangeName, instrumentType,
    firstTradeDate, timezone, gmtoffset` → `listing.currency`, `listing.timezone`,
    `listing.first_trade_date`.

### 2.2 Statements — `income_stmt`, `balance_sheet`, `cashflow` and quarterly / ttm

Built from Yahoo's fundamentals timeseries with fixed line-item keys,
`yfinance/const.py` `fundamentals_keys`: **103 income, 149 balance sheet, 123 cash
flow** items (e.g. `TotalRevenue, OperatingIncome, NormalizedEBITDA, NetDebt,
FreeCashFlow, ...`). Frame: rows = line items, columns = period end dates. Three
timescales: `annual`, `quarterly`, `trailing`.

**Model changes**

16. These are facts with Yahoo's own concept names. Load them as the `yahoo`
    taxonomy: 375 concepts, loaded from `const.py`, versioned by yfinance release.
    `fact.source = yahoo`, `concept_id = yahoo:TotalRevenue`, `period_end` = column
    date, `period_start` derived (annual = FYE−1y, quarterly = −3m, ttm = −12m),
    `statement_basis = as_reported`, `known_at = fetched_at`, `unit` = the
    `financialCurrency` from `info`.
17. Yahoo gives **no accession and no restatement flag**. Two fetches with different
    values for the same cell are two `fact` rows with different `known_at` and
    `raw_sha256`. The natural key in the SDD (`raw_sha256, concept_id, period_end,
    dimensions_key`) is right; add `timescale` to it, because annual and trailing can
    share a period end.

### 2.3 Profile and quote — `Ticker.info`

Merged from Yahoo quoteSummary modules (`yfinance/const.py`
`quote_summary_valid_modules`): `summaryProfile, summaryDetail, assetProfile,
price, quoteType, esgScores, financialData, defaultKeyStatistics,
calendarEvents, earnings, ...`. ~150 keys: `sector, industry, longBusinessSummary,
fullTimeEmployees, country, website, marketCap, enterpriseValue, trailingPE,
forwardPE, priceToBook, enterpriseToEbitda, beta, sharesOutstanding, floatShares,
dividendYield, currency, financialCurrency, exchange, quoteType, shortName,
longName, companyOfficers[] ...`. Keys are **not stable** across time or across
tickers.

**Model changes**

18. Store `info` as a **snapshot document**: `issuer_profile_snapshot(issuer_id,
    source=yahoo, fetched_at, raw_sha256, payload JSON, payload_schema=yahoo-info@1)`
    in SQLite. Pick stable fields into `issuer` (`sector`, `industry`, `employees`,
    `country`, `website`) and `listing` (`currency`, `exchange`). Yahoo's precomputed
    ratios (`trailingPE`, `enterpriseToEbitda`) go into `ratio` with
    `method_version = yahoo:<fetched_at>` so they are comparable with ours but never
    confused with them.

### 2.4 Holders and insiders

`major_holders` (pct insiders, pct institutions, float %, count),
`institutional_holders` and `mutualfund_holders` (`Date Reported, Holder, pctHeld,
Shares, Value`), `insider_transactions`, `insider_purchases`,
`insider_roster_holders`. Yahoo's insider data is a thinner copy of Form 4.

**Model changes**

19. `holder_position(issuer_id, holder_name, holder_kind institution|fund, report_date,
    shares, value, pct_held, source, raw_sha256)` in DuckDB. Insider data from Yahoo is
    not stored; Form 4 via edgartools is the record.

### 2.5 Actions, calendar, estimates, recommendations

`dividends, splits, capital_gains, actions` (date-indexed) → `corporate_action`
rows with `source = yahoo`. `calendar` (earnings dates, ex-dividend date) →
`corporate_action(kind = earnings_date | ex_dividend)`. `earnings_estimate,
revenue_estimate, eps_trend, eps_revisions, growth_estimates,
analyst_price_targets, recommendations, upgrades_downgrades` → **new**
`analyst_estimate(issuer_id, kind, period, metric, value, n_analysts, fetched_at,
raw_sha256)` in DuckDB. `news` → `document(source = yahoo, form = news)` with
`url`, `title`, `publisher`, `published_at`. `sec_filings` from Yahoo is ignored;
EDGAR is the record.

### 2.6 The Yahoo MCP fork — `yahoo-finance-mcp/server.py`

Nine tools returning `DataFrame.to_json(orient="records")` strings. Nothing stored.
Statement tool returns `[{date, <line item>: value, ...}]`, one object per period.
USERDATA uses it as the pattern for its *read* tools and calls yfinance directly for
storage.

---

## 3. Changes to the SDD, in one list

| # | Change | Where |
|---|---|---|
| 1 | `fact.decimals` text, not int | 5.3 |
| 2 | add `fact.source_fact_id`, `fact.context_ref`, `fact.frame`, `fact.timescale` | 5.3 |
| 3 | add `fact_footnote` | 5.3 |
| 4 | add `filing_concept_relation` (per-filing presentation/calculation/definition arcs) | 5.3 |
| 5 | `taxonomy.kind` adds `company`; one taxonomy per filer prefix | 5.3 |
| 6 | add quality columns `is_audited, is_estimated, data_quality, confidence` to `fact` | 5.3 |
| 7 | `known_at` + `known_at_precision` | 5.3, 5.5 |
| 8 | `document` gains report_date, file/film number, items JSON, size, primary_document, is_xbrl, is_inline_xbrl, act | 5.5 |
| 9 | add `attachment`; `chunk` points at attachment | 5.5 |
| 10 | `issuer` gains sic_description, ein, entity_type, category, website, phone, addresses; add `issuer_name` history | 5.1 |
| 11 | `listing.valid_from` means "first seen", stated; add currency, timezone, first_trade_date | 5.1 |
| 12 | OpenFIGI out of v1; `figi` stays in the scheme enum | 5.1, 10 |
| 13 | add `insider_transaction` and `person` | new 5.7 |
| 14 | `price_daily` gains dividends, stock_splits, capital_gains, repaired | 5.5 |
| 15 | `yahoo` taxonomy of 375 concepts loaded from yfinance const, versioned | 5.3 |
| 16 | add `issuer_profile_snapshot`; Yahoo ratios into `ratio` with `method_version = yahoo:<date>` | 5.1, 5.5 |
| 17 | add `holder_position`, `analyst_estimate`; news as documents | new 5.7 |
| 18 | corporate actions from Yahoo actions/calendar with `source = yahoo` | 5.1 |
| 19 | edgartools standardisation = `std` taxonomy + `concept_mapping` versioned by edgartools release | 5.3 |
| 20 | USERDATA calls the libraries for storage and borrows the MCP tools' shapes for its read tools | 6 |

Next step after Michael's review: apply these to `SDD.md`, section by section.
