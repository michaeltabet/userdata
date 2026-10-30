# USERDATA — Software Design Document

Draft 2, 2026-10-30, amended after Phase 0 build. Schema as built: `SCHEMA.md`. Draft 1 and its review are in
`archive/SDD-draft1.md` and `REVIEW-1.md`.

Contents: 1 Problem · 2 Load · 3 Use cases · 4 The one rule · 5 ERD and
rationale (5.6 is the research account: watchlists, peer groups, searches, notes) · 6 Sequence diagrams · 7 Transactions and invariants · 8 Physical
design now and later · 9 Evolution · 10 Decisions.

---

## 1. Problem

The tools exist. `edgartools` reads EDGAR and parses XBRL. `yfinance` reads
prices and fundamentals. Arelle validates taxonomies. Claude can call them all.
None of them keeps anything for the user. Yahoo Finance gives a logged-in user an
account: history, saved screens, watchlists, settings. USERDATA is that account for
Michael's work with Claude, done properly. It is the user's durable store,
exposed as MCP tools, used from Claude Desktop and Claude Code.

v1 runs on SQLite and DuckDB. Postgres, ClickHouse, dbt, Airflow, Unity Catalog,
NiFi and Superset come later and must slot in without rework. Permissive
licences only. Every write survives a kill and restart.

---

## 2. Load (DDIA ch. 1, "Describing Load")

Design load, not launch load. Numbers are for 100 companies followed over 3 years.

| What | Estimate | Basis |
|---|---|---|
| Issuers, securities, listings | 100 / 150 / 200 | some issuers have two share classes or more than one listing |
| Filings per issuer per year | 30 | 10-K, 3×10-Q, ~15 8-K, Form 4s, 13G, S-1 or S-3 when they raise money |
| Filings total | 9 000 | |
| XBRL facts per 10-K / 10-Q | 2 500 / 1 000 | typical edgartools output, with dimensions |
| Facts total (reported) | ~1.7 M | 100 × 3 × (2 500 + 3 000) |
| Facts total (derived + manual) | ~50 k | own concepts are few; per issuer per period |
| Chunks per 10-K / 10-Q / 8-K | 1 200 / 400 / 30 | ~500 tokens per chunk |
| Chunks total | ~900 k | ~2 KB text each → ~1.8 GB text |
| Embeddings | 900 k × 384 floats | ~1.4 GB; brute-force cosine scans in ~1 s on DuckDB |
| Price rows | 150 k | 200 listings × 252 days × 3 years |
| Ratios | ~200 k | 100 issuers × 12 quarters × ~150 ratio-method pairs |
| Events (user-authored changes) | ~20 k per year | preferences, tags, theses, questions, skill edits |
| Skill runs | ~5 k per year | |
| Sessions | ~1 k per year | |
| Searches | ~5 k per year | |
| Watchlists / peer groups / notes | 10s / 10s / 1 k per year | |

Consequence: everything above 100 k rows is columnar and append-mostly, so it
goes in DuckDB. Everything authored by a person or by Claude is small, needs
transactions and history, so it goes in SQLite. Chunk text is 1.8 GB, so it is
DuckDB, not SQLite.

---

## 3. Use cases

Actors: **Michael** (owns meaning), **Claude** (does the work), **Skill** (a
versioned procedure Claude runs), **Scheduler** (Airflow, later). Every write
records which actor made it.

| # | Use case | Actor | Writes to |
|---|---|---|---|
| 1 | Start and end a session; record notes, decisions, artifacts | Claude | event, session |
| 2 | Set a preference; see what was in force at a past date | Michael | event, preference_current |
| 3 | Register a skill; publish a new version; install it to disk | Michael, Claude | skill, skill_version, blob |
| 4 | Run a skill; store inputs, report, artifacts, and the preferences in force | Skill | skill_run, skill_report |
| 5 | Pull EDGAR / Yahoo / FIGI data; cache it; load it once | Claude, Scheduler | source_call, raw_payload, fact, price_daily, chunk |
| 6 | Resolve CIK ↔ ticker ↔ FIGI at a date; record company relations and corporate actions | Claude | issuer, security, listing, identifier_assignment, entity_relation, corporate_action |
| 7 | Define an own XBRL concept and its formula; validate with Arelle; publish | Michael | taxonomy_version, concept_version, concept_mapping |
| 8 | Derive own-concept facts from reported facts; compare | Skill | fact (origin=derived), fact_input |
| 9 | Type a number by hand as an own-concept fact | Michael | manual_fact → fact (origin=manual) |
| 10 | Tag a document, chunk or fact with an own tag | Michael, Skill | tag, *_tag |
| 11 | Compute ratios by versioned method; run a screen | Skill | ratio, ratio_input, screen_result |
| 12 | Semantic search over filing chunks with filters | Claude | reads chunk_embedding |
| 13 | Open, revise, close a thesis; add claims with kill criteria | Michael | thesis, thesis_version, thesis_claim |
| 14 | Queue a research question; work it step by step; answer with evidence | Michael, Claude | research_question, research_step, research_answer, evidence |
| 15 | A fact is restated: find every claim that cited it | Claude | reads evidence, fact |
| 16 | Rebuild every derived table from raw + events + code | Scheduler | all DuckDB tables |
| 17 | Save a screen; run it; score every company | Michael, Skill | screen_version, screen_result |
| 18 | Build a peer group by hand, by SIC, or from a screen | Michael, Claude | peer_group, peer_group_member |
| 19 | Keep watchlists; see when and why a company was added or dropped | Michael | watchlist, watchlist_item |
| 20 | See my search history; save and rerun a search | Michael | search_history, saved_search |
| 21 | Write notes on a company; compare peers side by side | Michael, Claude | company_note, comparison |
| 22 | Start a project; put sessions, theses, lists, notes and runs under it; pick it up days later | Michael, Claude | project |

---

## 4. The one rule: record or derived

DDIA Part III: decide for every piece of data whether it is the **system of
record** (SoR) or **derived** from something else. Draft 1 did not. Draft 2
does, table by table.

- **SoR** = cannot be rebuilt. Authored by Michael or Claude, or fetched once
  from outside and immutable (raw payloads). Lives in SQLite, later Postgres.
  Backed up. History kept.
- **Derived** = a pure function of (SoR data, raw payloads, code version). Lives
  in DuckDB, later ClickHouse. Rebuildable by replay. Not backed up.
- **Reference** = fetched from outside but curated (identity, relations). SoR
  with a `source_call_id` saying where each row came from.

Writes follow DDIA ch. 11 and 12, not dual writes:

1. A tool call is a **command**. It commits **one SQLite transaction**: the
   `event` row (the truth), the SoR or projection rows, and an `outbox` row if
   DuckDB must be updated.
2. A **projector** reads the outbox and loads DuckDB **idempotently**, keyed on
   natural keys, and writes a `load_log` row in the same DuckDB transaction.
3. A cache hit means the `load_log` row exists for (payload, code version,
   table), not just that `source_call` says "fetched".
4. Files on disk (taxonomy `.xsd`, skills in `~/.claude/skills`, report files)
   are **exports** of database rows, never the other way round.

Two projections are allowed to be synchronous for simplicity: `session` and
`preference_current` are written in the same SQLite transaction as their event.
A replay test rebuilds them from `event` and must match.

Cross-store references (SQLite row → DuckDB row, or back) cannot be foreign
keys. They use **deterministic ids** (sha256 of the natural key), are checked
for existence at write time, and are re-checked by a nightly integrity query.
ClickHouse has no foreign keys either, so this is the habit from day one.

---

## 5. ERD and rationale (DDIA ch. 2, 3, 4, 7, 11)

Five domains. Each diagram shows its SQLite tables and the DuckDB tables it
references. DuckDB tables are named in the diagram with the comment
`"DuckDB"` on their id column. Relationships labelled `xstore` cross the store
boundary and are deterministic ids, not foreign keys.

Every id is either a deterministic hash of the natural key (written as
`sha256(...)`) or a UUIDv7 (time-ordered, so B-tree inserts stay sequential,
DDIA ch. 3). Dates are ISO-8601 UTC text with a `Z` suffix in SQLite, enforced
by `CHECK`, and real `DATE` / `TIMESTAMP` in DuckDB.

### 5.1 Identity and reference

```mermaid
erDiagram
  issuer ||--o{ security : "issues"
  security ||--o{ listing : "listed_as"
  issuer ||--o{ identifier_assignment : "identified"
  security ||--o{ identifier_assignment : "identified"
  listing ||--o{ identifier_assignment : "identified"
  issuer ||--o{ entity_alias : "survivor"
  issuer ||--o{ entity_relation : "from_side"
  issuer ||--o{ entity_relation : "to_side"
  issuer ||--o{ corporate_action : "acts"
  issuer ||--o{ fiscal_period : "reports_in"
  source_call ||--o{ issuer : "resolved_by"
  source_call ||--o{ identifier_assignment : "resolved_by"

  issuer {
    text issuer_id PK "cik:0000000000 when a CIK exists, else uuid7"
    text name
    text cik UK "nullable"
    text lei "nullable"
    text sic
    text state_of_inc
    text fye_mmdd "fiscal year end, e.g. 1231"
    text source_call_id FK
    text recorded_at
  }
  security {
    text security_id PK "uuid7"
    text issuer_id FK
    text kind "common | preferred | when_issued | adr | unit"
    text class_name "nullable, e.g. Class A"
    text isin UK "nullable"
    text cusip UK "nullable"
    text figi_share_class "nullable"
    text recorded_at
  }
  listing {
    text listing_id PK "uuid7"
    text security_id FK
    text exchange_mic "XNAS, XNYS"
    text ticker
    text figi_exchange "nullable"
    bool when_issued
    text valid_from
    text valid_to "9999-12-31 when open"
    text source_call_id FK
  }
  identifier_assignment {
    text assignment_id PK "uuid7"
    text scheme "cik | lei | isin | cusip | figi | ticker"
    text value
    text level "issuer | security | listing"
    text target_id "id at that level"
    text valid_from
    text valid_to "9999-12-31 when open; no overlap per scheme+value"
    text source_call_id FK
    text recorded_at
  }
  entity_alias {
    text merged_issuer_id PK
    text survivor_issuer_id FK
    text merged_at
    text reason
  }
  entity_relation {
    text relation_id PK "uuid7"
    text from_issuer_id FK
    text to_issuer_id FK
    text kind "parent | spun_off_from | predecessor | subsidiary | acquirer"
    text effective_on
    text source_call_id FK
    text note
  }
  corporate_action {
    text action_id PK "uuid7"
    text issuer_id FK
    text security_id FK "nullable"
    text kind "split | dividend | distribution | ticker_change | merger"
    real ratio_num
    real ratio_den
    text declared_on
    text record_on
    text ex_on
    text effective_on
    text wi_start "when-issued window, nullable"
    text wi_end
    text form8937_document_id "nullable"
    text source_call_id FK
  }
  fiscal_period {
    text fiscal_period_id PK "issuer_id:FY2025:Q2"
    text issuer_id FK
    int fiscal_year
    text fiscal_period "FY | Q1 | Q2 | Q3"
    text period_start
    text period_end
    text from_accession "DEI source"
  }
  source_call {
    text call_id PK
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `issuer` | Reference | the legal filer | by id; by CIK; by name search | 100s | Relational. The id is the CIK when there is one, so resolving the same company by ticker and later by CIK cannot mint two rows (DDIA ch. 2: ids separate from human-meaningful values; ch. 11 idempotence). |
| `security` | Reference | one instrument of an issuer | by issuer | 100s | Relational, 1:N from issuer. ISIN, CUSIP and share-class FIGI live here, not on the issuer, because GOOG and GOOGL are two securities of one issuer. |
| `listing` | Reference | one ticker on one exchange, over time | by (ticker, exchange, date); by security | 100s | Relational, 1:N from security, temporal. Prices and ratios key on listing, because two listings of one security can trade at different prices on the same day. |
| `identifier_assignment` | Reference | every external id, at its real level, with validity | find target by (scheme, value, date) | 1 000s | One table for all schemes so the no-overlap rule is one trigger: a ticker cannot belong to two targets on the same day. Knowledge time is `recorded_at` + `source_call_id`; full bitemporal queries are not needed here (DDIA ch. 11, event time vs processing time). |
| `entity_alias` | SoR | merge two issuers found to be one | by merged id on every lookup | 10s | Without it, a wrong early resolution can never be repaired without rewriting keys. |
| `entity_relation` | Reference | how companies relate | children of X; parents of X; path | 100s | Graph as edge table, walked with a recursive CTE (DDIA ch. 2, graph in SQL). Same pattern as concept relations. |
| `corporate_action` | Reference | splits, dividends, ticker changes, mergers, distributions | by issuer and date | 100s | This is what makes `adj_close` checkable and what dates a corporate action took effect. Form 8937 cost-basis allocation points at its document. |
| `fiscal_period` | Derived | what "FY2025 Q2" means for this issuer | by id from facts | 1 000s | Derived from DEI `DocumentFiscalPeriodFocus`. Small enough for SQLite, needed as a key by DuckDB facts, so the id is deterministic. Solves non-December year ends and 52/53-week years. |

### 5.2 Authored state: events, sessions, preferences, skills

```mermaid
erDiagram
  actor ||--o{ event : "recorded_by"
  event ||--o| outbox : "projects"
  actor ||--o{ session : "runs"
  event ||--o{ preference_current : "set_by"
  skill ||--o{ skill_version : "versions"
  skill_version ||--o{ skill_version_file : "files"
  blob ||--o{ skill_version_file : "content"
  skill_version ||--o{ skill_run : "executed"
  session o|--o{ skill_run : "hosts"
  actor ||--o{ skill_run : "ran_by"
  event ||--o{ skill_run : "as_of"
  skill_run ||--o| skill_report : "produces"
  skill_run ||--o{ report_file : "artifacts"
  blob ||--o{ report_file : "content"

  actor {
    text actor_id PK "michael | claude | skill:ID | scheduler"
    text kind "human | agent | skill | scheduler"
    text name
  }
  event {
    text event_id PK "uuid7, generated by the client; idempotency key"
    text stream "preference:global | session:ID | thesis:ID | skill:ID | taxonomy:mt | question:ID"
    int stream_seq
    text type "preference_set | session_started | thesis_opened | ..."
    int type_version
    json payload
    text payload_schema "name@version"
    text actor_id FK
    text causation_id "event that caused this one, nullable"
    text correlation_id "session_id usually"
    text recorded_at
  }
  outbox {
    text outbox_id PK
    text event_id FK
    text target "duckdb"
    text status "pending | done | failed"
    text created_at
    text processed_at
  }
  session {
    text session_id PK "projection of session events"
    text actor_id FK
    text client "claude-code | claude-desktop"
    text started_at
    text ended_at "nullable"
    text title
    json context
  }
  preference_current {
    text scope PK "global | skill:ID | issuer:ID"
    text key PK
    json value
    text value_schema
    text event_id FK "the preference_set event that produced this row"
    text updated_at
  }
  skill {
    text skill_id PK "uuid7"
    text name UK
    text purpose
    text current_version_id FK "projection"
    text created_at
  }
  skill_version {
    text skill_version_id PK "uuid7"
    text skill_id FK
    int version
    text parent_version_id FK "nullable"
    text manifest_sha256 "sha256 over sorted rel_path+blob pairs"
    json props
    text props_schema
    text created_by FK
    text created_at
  }
  blob {
    text sha256 PK
    blob bytes
    text media_type
    int size
  }
  skill_version_file {
    text skill_version_id PK
    text rel_path PK "SKILL.md, references/x.md, scripts/y.py"
    text blob_sha256 FK
  }
  skill_run {
    text run_id PK "uuid7"
    text skill_version_id FK
    text session_id FK "nullable: scheduled runs have none"
    text actor_id FK
    text started_at
    text ended_at
    text status "running | ok | failed | partial"
    json inputs
    text inputs_schema
    text as_of_event_id FK "last event seen when the run started"
  }
  skill_report {
    text run_id PK
    text summary
    json body
    text body_schema
    text created_at
  }
  report_file {
    text run_id PK
    text rel_path PK
    text blob_sha256 FK
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `event` | **SoR** | every change Michael or Claude makes | by stream in order; replay all | 20 k/yr | Event sourcing (DDIA ch. 11): the log is the truth, tables are caches of it. `event_id` is generated by the client so MCP retries are idempotent. `type_version` is the upcasting hook. `actor` answers "who decided this". No snapshots: the log is small enough to replay in seconds. |
| `outbox` | SoR | hand events to the DuckDB projector | pending by created_at | small, churns | Transactional outbox (DDIA ch. 11, "Keeping systems in sync"): written in the same transaction as the event, so DuckDB can never miss a change and never sees one that was rolled back. |
| `actor` | SoR | who | by id | 10s | Michael, Claude, each skill, the scheduler. Every SoR row carries one. |
| `session` | Projection | a working session | by id; recent | 1 k/yr | Rebuilt from `session_started` / `session_ended` / `session_titled` events. Synchronous projection for simplicity. |
| `preference_current` | Projection | what is in force now | by (scope, key); all in scope | 100s | The history is in `event`. "What did Claude know about Michael when it wrote this report" = events in `preference:*` streams up to `skill_run.as_of_event_id`. Scope makes a preference global, per skill or per issuer. |
| `skill` | SoR | a skill's identity | by name | 10s | `current_version_id` is a projection of `skill_published` events. |
| `skill_version` | **SoR** | one immutable version of a skill | latest per skill; by id from a run | 100s | Insert-only. Database is the source of truth for skills; the folder in `~/.claude/skills` is an export. `parent_version_id` gives the lineage of edits. Props are a document with a schema id (DDIA ch. 4). |
| `blob` | **SoR** | bytes, content-addressed | by hash | 1 000s | One store for skill files and report artifacts. Identical files stored once. |
| `skill_version_file` | SoR | the bundle | all files of a version | 1 000s | A skill is SKILL.md plus references plus scripts. One row per file. |
| `skill_run` | **SoR** | the lineage anchor | by id; by skill; by session | 5 k/yr | Facts, ratios, taggings, source calls and research steps point back here. `as_of_event_id` pins the preferences and skill text that were in force. |
| `skill_report` | SoR | what the run concluded | by run | 5 k/yr | Document: written once, read whole. Artifacts go to `blob` via `report_file`, never to a path. |

### 5.3 Concepts and facts

```mermaid
erDiagram
  taxonomy ||--o{ taxonomy_version : "versions"
  taxonomy ||--o{ concept : "defines"
  concept ||--o{ concept_version : "versions"
  taxonomy_version ||--o{ concept_version : "contains"
  taxonomy_version ||--o{ concept_relation : "arcs"
  concept ||--o{ concept_relation : "from_side"
  concept ||--o{ concept_relation : "to_side"
  taxonomy_version ||--o{ concept_mapping : "formulas"
  concept ||--o{ concept_mapping : "target"
  concept ||--o{ concept_mapping : "input"
  issuer o|--o{ concept_mapping : "scoped"
  concept ||--o{ manual_fact : "typed_as"
  issuer ||--o{ manual_fact : "about"
  event ||--o{ manual_fact : "entered_by"
  blob o|--o{ taxonomy_version : "arelle_report"
  manual_fact ||--o| fact : "xstore"
  concept_version o|--o{ fact : "xstore"
  taxonomy_version o|--o{ fact : "xstore"
  fact ||--o{ fact_input : "derived_from"
  fact ||--o{ fact_input : "input"
  fact o|--o{ statement_line : "xstore"
  load_log ||--o{ fact : "loaded_in"

  taxonomy {
    text taxonomy_id PK "us-gaap-2025 | dei-2025 | yahoo | std | mt"
    text prefix UK
    text namespace_uri
    text kind "base | vendor | standard | own"
  }
  taxonomy_version {
    text taxonomy_version_id PK "uuid7"
    text taxonomy_id FK
    int version
    text status "draft | validated | published"
    text arelle_report_sha256 FK "nullable"
    text created_by FK
    text created_at
    text published_at "nullable"
  }
  concept {
    text concept_id PK "the qname, e.g. mt:AdjustedEbitda"
    text taxonomy_id FK
    text local_name
  }
  concept_version {
    text concept_version_id PK "uuid7"
    text concept_id FK
    text taxonomy_version_id FK
    text data_type "monetary | shares | perShare | string"
    text period_type "duration | instant"
    text balance "debit | credit | none"
    bool abstract
    text definition
    json labels "role -> lang -> text"
  }
  concept_relation {
    text taxonomy_version_id PK
    text from_concept_id PK
    text to_concept_id PK
    text arcrole PK "parent-child | summation-item | dimension-domain"
    real weight
    int order_no
  }
  concept_mapping {
    text mapping_id PK "uuid7"
    text taxonomy_version_id FK
    text target_concept_id FK "mt:AdjustedEbitda"
    text input_concept_id FK "us-gaap:OperatingIncomeLoss, yahoo:TotalRevenue"
    text scope_issuer_id FK "nullable: issuer-specific override"
    real weight
    int sign
    text period_rule "same | ttm | annualise"
    text note
  }
  manual_fact {
    text manual_fact_id PK "uuid7"
    text concept_id FK
    text issuer_id FK
    text period_start "nullable for instants"
    text period_end
    text unit
    real value
    json dimensions
    text statement_basis
    text basis_note "where the number came from, in words"
    text event_id FK
    text actor_id FK
    text created_at
  }
  fact {
    text fact_row_id PK "DuckDB. sha256 of the natural key"
    text origin "reported | derived | manual"
    text source "edgar | yahoo | mt"
    text issuer_id "xstore"
    text accession "nullable for yahoo and manual"
    text concept_id "qname; xstore"
    text concept_version_id "xstore, nullable for base taxonomies"
    date period_start "nullable for instants"
    date period_end
    text fiscal_period_id "xstore, nullable"
    text unit
    json dimensions
    text dimensions_key "canonical axis=member;... string; empty for none"
    double value
    int decimals
    text statement_basis "as_reported | restated | pro_forma | carve_out"
    timestamp known_at "EDGAR acceptance time, or fetched_at"
    text raw_sha256 "payload this came from"
    text mapping_taxonomy_version_id "for derived"
    text code_version
    text load_batch_id
  }
  fact_input {
    text fact_row_id PK "the derived fact"
    text input_fact_row_id PK
    real weight
  }
  statement_line {
    text line_row_id PK "DuckDB. sha256(accession, statement, line_no, code_version)"
    text accession
    text statement "income | balance | cashflow | equity | comprehensive"
    int line_no
    text label "as presented"
    text concept_id
    text fact_row_id "nullable for abstract rows"
    text raw_sha256
    text code_version
  }
  load_log {
    text load_batch_id PK "DuckDB"
    text input_ref "raw_sha256 or event_id"
    text code_version
    text target_table
    int row_count
    timestamp loaded_at
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `taxonomy` | SoR | a namespace | by prefix | 5 | Base (us-gaap, dei), vendor (yahoo line items), standard (edgartools' standardised labels) and own (`mt`) are all taxonomies. That is what lets an `mt` arc point at a `us-gaap` concept. |
| `taxonomy_version` | **SoR** | a validated snapshot of a taxonomy | published per taxonomy; by id from a fact | 10s | Draft → validated by Arelle → published. Only published versions can be referenced by mappings and facts (DDIA ch. 7: invariants as constraints). Arelle's report is kept as a blob. |
| `concept` | SoR | a concept's identity | by qname | 20 k | Base taxonomies are loaded so arcs, mappings and facts have something to reference. The id is the qname, so it is deterministic. |
| `concept_version` | **SoR** | what a concept meant in one taxonomy version | by concept; by version | 20 k | Insert-only. Editing a definition cannot change the meaning of old facts, because they point at the old version. |
| `concept_relation` | SoR | the taxonomy graph | children; parents; calculation tree | 50 k | Graph as edge table, keyed by taxonomy version. Recursive CTE in SQLite and Postgres. |
| `concept_mapping` | **SoR** | **the formula as data** | all inputs of a target; all targets using an input | 100s | `mt:AdjustedEbitda = +1 × us-gaap:OperatingIncomeLoss +1 × mt:OneOffCosts`. One row per input. `scope_issuer_id` allows a per-company override. Derived facts are a pure function of this table plus reported facts plus code version (DDIA ch. 10). The reverse lookup "which own concepts depend on this us-gaap concept" is a plain join. |
| `manual_fact` | **SoR** | a number Michael typed | by concept and issuer | 1 000s | Hand-entered values cannot be rebuilt, so they are SoR in SQLite, with the event that entered them. Projected into `fact` with `origin=manual`. |
| `fact` | **Derived** | **one long table for every number**, reported or derived or manual | by issuer, concept, period; by concept across issuers; latest vs as-first-reported | 1.7 M | DDIA ch. 3: the narrow fact table is the columnar shape; DDIA ch. 2: one family of data in one place so comparisons are a join, not a cross-engine union. `known_at` + `accession` give point-in-time reads: `fact_latest` and `fact_as_of(date)` views (ch. 11, event time vs processing time). `statement_basis` separates pro forma and carve-out numbers from as-reported ones. `dimensions_key` is the canonical string so dimensions can be part of the key and, later, of the ClickHouse `ORDER BY`. |
| `fact_input` | Derived | lineage of a derived fact | inputs of X; what was built from Y | 100 k | Which reported rows went into an own-concept value. Auditable without recomputing. When a fact is restated, this finds every derived fact to recompute. |
| `statement_line` | Derived | how a filing presented its numbers | by accession and statement, in order | 500 k | Presentation is separate from facts (that is how XBRL itself is built). "Tag a statement line" means tagging the fact the line shows. |
| `load_log` | Derived | proof that a payload was loaded by a code version | by (input_ref, code_version, table) | 10 k | Written in the same DuckDB transaction as the rows. The cache check reads this, not `source_call`. A parser fix means: find batches with the old code version, reload only those (DDIA ch. 10, reproducible batch outputs). |

**Natural keys** (what `fact_row_id` hashes):

| origin / source | natural key |
|---|---|
| reported / edgar | accession, concept_id, period_start, period_end, unit, dimensions_key |
| reported / yahoo | raw_sha256, concept_id, period_end, dimensions_key |
| derived / mt | mapping_taxonomy_version_id, target concept_id, issuer_id, period_start, period_end, unit, dimensions_key, code_version, sorted input fact_row_ids |
| manual / mt | manual_fact_id |

### 5.4 Tags, theses, research, evidence

```mermaid
erDiagram
  actor ||--o{ tag : "owns"
  tag ||--o{ document_tag : "applied"
  tag ||--o{ chunk_tag : "applied"
  tag ||--o{ fact_tag : "applied"
  document ||--o{ document_tag : "tagged"
  skill_run o|--o{ document_tag : "by_run"
  issuer o|--o{ thesis : "subject"
  entity_relation o|--o{ thesis : "subject_pair"
  thesis ||--o{ thesis_version : "versions"
  thesis ||--o{ thesis_claim : "claims"
  thesis_claim ||--o{ evidence : "supported_by"
  document o|--o{ evidence : "cites"
  thesis o|--o{ research_question : "serves"
  thesis_claim o|--o{ research_question : "tests"
  actor ||--o{ research_question : "assigned"
  research_question ||--o{ research_step : "steps"
  skill_run o|--o{ research_step : "used_run"
  source_call o|--o{ research_step : "used_call"
  research_question ||--o| research_answer : "answered"
  research_answer ||--o{ evidence : "created"

  tag {
    text tag_id PK "uuid7"
    text namespace UK "mt | skill:ID"
    text name UK
    text description
    text actor_id FK
    text created_at
  }
  document_tag {
    text tag_id PK
    text document_id PK
    text run_id FK "nullable"
    text note
    text created_at
  }
  chunk_tag {
    text tag_id PK
    text chunk_id PK "DuckDB chunk; xstore"
    text run_id FK "nullable"
    text note
    text created_at
  }
  fact_tag {
    text tag_id PK
    text fact_row_id PK "DuckDB fact; xstore"
    text run_id FK "nullable"
    text note
    text created_at
  }
  thesis {
    text thesis_id PK "uuid7"
    text subject_issuer_id FK "nullable"
    text subject_relation_id FK "nullable: a pair of related companies"
    text stance "long | short | watch | avoid"
    text status "draft | active | closed | invalidated; projection"
    text current_version_id FK "projection"
    text opened_on
    text closed_on "nullable"
    text actor_id FK
  }
  thesis_version {
    text thesis_version_id PK "uuid7"
    text thesis_id FK
    int version
    text body "the thesis text at this point in time"
    text created_by FK
    text created_at
  }
  thesis_claim {
    text claim_id PK "uuid7"
    text thesis_id FK
    text kind "catalyst | valuation | risk | structure"
    text statement
    text kill_criterion "what would prove it wrong"
    text status "open | supported | refuted; projection"
    text opened_on
    text resolved_on "nullable"
  }
  evidence {
    text evidence_id PK "uuid7"
    text claim_id FK
    text role "supports | contradicts | context"
    text note
    text chunk_id "exactly one of the four is set"
    text fact_row_id
    text ratio_row_id
    text document_id FK
    text answer_question_id FK "nullable: the answer that created it"
    text created_by FK
    text created_at
  }
  research_question {
    text question_id PK "uuid7"
    text thesis_id FK "nullable"
    text claim_id FK "nullable"
    text question
    int priority
    text status "open | in_progress | answered | dropped; projection"
    text assignee_actor_id FK
    text created_at
  }
  research_step {
    text step_id PK "uuid7"
    text question_id FK
    int seq
    text actor_id FK
    text run_id FK "nullable"
    text call_id FK "nullable"
    text finding
    text next_step
    text recorded_at
  }
  research_answer {
    text question_id PK
    text answer
    text answered_by FK
    text answered_at
    text event_id FK
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `tag` | SoR | an own label | by (namespace, name) | 100s | Namespace separates Michael's tags from skill-generated ones. |
| `document_tag`, `chunk_tag`, `fact_tag` | SoR | tag applied to one kind of target | tags of X; targets with tag T | 10 k | One join table per target kind, not `target_kind + target_id` (DDIA ch. 2: the relational model needs real references; polymorphic ids give no integrity and different queries per kind). `document_tag` has a true FK. The other two cross the store and use deterministic ids. |
| `thesis` | SoR | one investment idea | active list; by subject | 10s | Subject is an issuer or a relation between two issuers. Status and current version are projections of thesis events. |
| `thesis_version` | **SoR** | what Michael believed at a date | latest; diff two | 100s | Insert-only. History is the product (DDIA ch. 11). Same pattern as `skill_version`. |
| `thesis_claim` | SoR | one testable statement with its kill criterion | claims of a thesis; open claims everywhere | 100s | Claims are rows, not paragraphs, because research works against them one by one. |
| `evidence` | **SoR** | one link from a claim to a source | evidence for a claim; **which claims cite this fact or chunk** | 1 000s | M:N between claims and sources, with an exclusive arc: `CHECK` exactly one of `chunk_id`, `fact_row_id`, `ratio_row_id`, `document_id` is set. The reverse lookup is the reason it is relational: when a fact is restated, every claim that cited it must surface (use case 15). |
| `research_question` | SoR | the unit of research work | open queue by priority; by thesis | 100s | A queue Claude picks from in every session without being re-told. |
| `research_step` | **SoR** | what was done for a question | steps in order | 1 000s | Append-only log keyed by question. Points at the skill run or source call it used. The trail is the product. |
| `research_answer` | SoR | closes a question | by question | 100s | 1:1 with an answered question. Kept separate so answering is one transaction: answer + evidence + status event together (DDIA ch. 7). |

### 5.5 Documents, cache, chunks, prices, ratios, screens

```mermaid
erDiagram
  actor ||--o{ source_call : "made_by"
  skill_run o|--o{ source_call : "during"
  raw_payload o|--o{ source_call : "stored_as"
  raw_payload ||--o{ document : "content"
  issuer o|--o{ document : "filed_by"
  document ||--o{ chunk : "xstore"
  chunk ||--o{ chunk_embedding : "vectors"
  raw_payload ||--o{ load_log : "loaded"
  listing ||--o{ price_daily : "xstore"
  issuer ||--o{ ratio : "xstore"
  listing o|--o{ ratio : "xstore"
  ratio ||--o{ ratio_input : "inputs"
  skill_run o|--o{ ratio : "xstore"
  screen ||--o{ screen_version : "versions"
  screen_version ||--o{ screen_result : "xstore"
  listing ||--o{ screen_result : "xstore"

  source_call {
    text call_id PK "uuid7"
    text source "edgar | yahoo | figi"
    text endpoint
    json params "canonical: sorted keys, defaults filled, tickers upper-cased"
    text params_sha256
    text requested_at
    int http_status
    text error_class "nullable: rate_limited | not_found | upstream | network"
    text raw_sha256 FK "nullable on error"
    int ttl_seconds
    int negative_ttl_seconds "how long to trust an error"
    text run_id FK "nullable"
    text actor_id FK
  }
  raw_payload {
    text raw_sha256 PK
    text path "raw/source/sha256 prefix dirs"
    int bytes
    text content_type
    text first_seen_at
  }
  document {
    text document_id PK "accession when EDGAR, else sha256"
    text issuer_id FK "nullable for user documents"
    text source "edgar | yahoo | user"
    text form
    text accession UK "nullable"
    text filed_on
    text accepted_at "EDGAR acceptance datetime = known_at"
    text url
    text raw_sha256 FK
    text title
    text parser_version
  }
  chunk {
    text chunk_id PK "DuckDB. sha256(document_id, chunker_version, ordinal)"
    text document_id
    text issuer_id
    int ordinal
    text section "Item 1A, Item 7, note 12"
    int char_start
    int char_end
    text text
    int n_tokens
    text chunker_version
    text raw_sha256
  }
  chunk_embedding {
    text chunk_id PK "DuckDB"
    text model PK "all-MiniLM-L6-v2"
    text chunker_version PK
    int dim
    float[] vector
    text issuer_id "denormalised for filtering"
    text document_id
    text form
    date filed_on
    text section
    timestamp created_at
  }
  price_daily {
    text price_row_id PK "DuckDB. sha256(listing_id, trade_date, source)"
    text listing_id
    date trade_date
    double open
    double high
    double low
    double close
    double adj_close
    bigint volume
    text source
    timestamp known_at
    text raw_sha256
    text code_version
  }
  fx_rate {
    text base PK "DuckDB"
    text quote PK
    date rate_date PK
    double rate
    text source
    text raw_sha256
  }
  ratio {
    text ratio_row_id PK "DuckDB. sha256(issuer_id, listing_id, ratio_name, method_version, as_of)"
    text issuer_id
    text listing_id "nullable for non-price ratios"
    text ratio_name "pe | ev_ebitda | fcf_yield | net_debt_ebitda"
    text method_version
    date as_of "knowledge cut-off: only facts known_at <= as_of"
    date price_date "nullable"
    double value
    text run_id
    text code_version
  }
  ratio_input {
    text ratio_row_id PK "DuckDB"
    text input_kind PK "fact | price | fx"
    text input_row_id PK
    text role "numerator | denominator | adjustment"
  }
  screen {
    text screen_id PK "uuid7"
    text name UK
    text current_version_id FK
  }
  screen_version {
    text screen_version_id PK "uuid7"
    text screen_id FK
    int version
    json rules
    text rules_schema
    text created_by FK
    text created_at
  }
  screen_result {
    text screen_version_id PK "DuckDB"
    text listing_id PK
    date as_of PK
    bool passed
    double score
    text run_id
    text code_version
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `source_call` | SoR | every outside call, success or error | latest successful by params hash; errors within negative TTL | 50 k/yr | Many calls to one payload (`}o--o|`): content addressing means a re-fetch that returns the same bytes adds a call row, not a payload. Two different payloads for the same params is how a Yahoo revision becomes visible. Params are canonicalised by one tested function, or the hash misses. |
| `raw_payload` | **SoR** | the bytes as received, never edited | by hash | 30 k | Immutable inputs plus versioned code equals reproducible outputs (DDIA ch. 10). Everything in DuckDB can be rebuilt from here plus `event`. Copied to B2 by rclone, because one disk is not durable. |
| `document` | Derived | a filing or user document | by issuer and form; by accession | 10 k | Small, keyed by accession, referenced by FKs from `evidence` and `document_tag`, so it lives in SQLite although it is derived. `accepted_at` is the knowledge time for all its facts. |
| `chunk` | Derived | the text unit | by id from a search hit; by document in order | 900 k | 1.8 GB of text is a columnar store's job. `char_start/end` anchor citations. `chunker_version` in the id so a new chunker is additive. |
| `chunk_embedding` | Derived | the vector index | nearest k with filters | 900 k | Filter columns are **denormalised in** (issuer, form, date, section) because a vector index must carry what its readers filter on (DDIA ch. 3, ch. 12). Otherwise every search joins across stores or post-filters to fewer than k. Key includes model and chunker version so re-embedding is additive. v1 brute-force cosine: no index to persist, so rule 2 holds trivially. |
| `price_daily` | Derived | prices per listing per day | range by listing and date | 150 k | Keyed by listing, not issuer (when-issued vs regular way). `known_at` + `raw_sha256` make revisions visible instead of overwriting. |
| `fx_rate` | Derived | currency conversion | by pair and date | 10 k | Facts are stored in reporting currency; ratios convert at computation time and record the fx row they used. |
| `ratio` | Derived | a computed number by a named method | by issuer and as_of; one ratio across issuers | 200 k | Computed by versioned code from `fact` and `price_daily`. Claude picks the method, it does not supply numbers. `as_of` is the knowledge cut-off, so a screen as of a past date has no look-ahead (DDIA ch. 11). |
| `ratio_input` | Derived | every number a ratio used | inputs of a ratio; ratios using a fact | 1 M | Child table, not JSON: the reverse lookup "which ratios used this restated fact" needs rows. |
| `screen`, `screen_version` | SoR | a screen definition, versioned | current; by id from a result | 10s | Rules are a document with a schema id. Insert-only versions, same as skills and theses. |
| `screen_result` | Derived | pass/fail and score per listing per date | by screen and date | 100 k | Rebuildable from ratios and the screen version. |

### 5.6 The research account: watchlists, peer groups, searches, notes, comparisons

This is the part a Yahoo Finance account gives you, done properly: what you
watch, who you compare against, what you searched, what you wrote. All SoR in
SQLite, all changed through events, so every list has a history.

```mermaid
erDiagram
  actor ||--o{ watchlist : "owns"
  watchlist ||--o{ watchlist_item : "contains"
  issuer ||--o{ watchlist_item : "listed"
  skill_run o|--o{ watchlist_item : "added_by"
  actor ||--o{ peer_group : "owns"
  issuer o|--o{ peer_group : "anchor"
  screen_version o|--o{ peer_group : "built_from"
  peer_group ||--o{ peer_group_member : "members"
  issuer ||--o{ peer_group_member : "member"
  session o|--o{ search_history : "during"
  actor ||--o{ search_history : "searched"
  actor ||--o{ saved_search : "owns"
  saved_search o|--o{ search_history : "reran"
  issuer ||--o{ company_note : "about"
  actor ||--o{ company_note : "wrote"
  company_note o|--o| company_note : "supersedes"
  peer_group o|--o{ comparison : "compares"
  actor ||--o{ comparison : "owns"
  skill_run o|--o{ comparison : "computed_by"

  watchlist {
    text watchlist_id PK "uuid7"
    text name UK
    text purpose
    text actor_id FK
    text created_at
    text archived_at "nullable"
  }
  watchlist_item {
    text watchlist_id PK
    text issuer_id PK
    text added_at PK "same issuer can be re-added later"
    text removed_at "nullable: still on the list"
    text reason
    text run_id FK "nullable: the screen run that added it"
  }
  peer_group {
    text peer_group_id PK "uuid7"
    text name UK
    text anchor_issuer_id FK "nullable: the company the peers are for"
    text basis "manual | sic | screen | skill"
    text screen_version_id FK "nullable"
    text actor_id FK
    text created_at
  }
  peer_group_member {
    text peer_group_id PK
    text issuer_id PK
    real weight "nullable"
    text reason
    text added_at
    text removed_at "nullable"
  }
  search_history {
    text search_id PK "uuid7; projection of search events"
    text session_id FK "nullable"
    text actor_id FK
    text kind "semantic | filing | company | market | screen"
    text query
    json params
    text params_schema
    int result_count
    json top_result_ids
    text saved_search_id FK "nullable"
    text searched_at
  }
  saved_search {
    text saved_search_id PK "uuid7"
    text name UK
    text kind
    json params
    text params_schema
    text actor_id FK
    text created_at
  }
  company_note {
    text note_id PK "uuid7"
    text issuer_id FK
    text body
    bool pinned
    text supersedes_note_id FK "nullable: edits are new notes"
    text actor_id FK
    text created_at
  }
  comparison {
    text comparison_id PK "uuid7"
    text name
    text peer_group_id FK "nullable: or an explicit issuer list in params"
    json params "metrics, periods, basis"
    text params_schema
    text as_of "knowledge cut-off"
    text run_id FK "nullable: the run that computed it"
    text actor_id FK
    text created_at
  }
```

| Table | Kind | For | Read how | Rows | Shape and why |
|---|---|---|---|---|---|
| `watchlist`, `watchlist_item` | **SoR** | what you follow, and since when | items of a list; lists containing X; what was dropped and why | 10s / 100s | `added_at` is part of the key and `removed_at` is a column, so a drop is not a delete: "when did I drop it and why" stays answerable (DDIA ch. 11, immutability). An item can point at the screen run that put it there. |
| `peer_group`, `peer_group_member` | **SoR** | who you compare a company against | members of a group; groups containing X | 10s / 100s | A group has an anchor company and a basis: by hand, by SIC code, from a screen, or from a skill. Membership keeps `removed_at` like watchlists. Weight allows weighted peer medians later. |
| `search_history` | Projection | your history of searches | recent; by session; by kind; by company | 5 k/yr | Projected from `search_performed` events, so it is rebuildable and the event log stays the truth. `top_result_ids` lets you reopen what you found without re-running. |
| `saved_search` | SoR | a search you want to rerun | by name | 10s | Params are a document with a schema id, same as screens. A rerun writes a `search_history` row pointing back here. |
| `company_note` | **SoR** | what you wrote about a company | notes of a company, newest first; pinned | 1 k/yr | Insert-only. An edit is a new note that supersedes the old one, so nothing you wrote is ever lost. |
| `comparison` | SoR | a saved side-by-side | by name; by peer group | 100s | The definition is the record. The numbers come from `ratio` and `fact` at `as_of`, so a comparison is reproducible and never stale: it recomputes from the same cut-off. |

**Project.** A `project(project_id, name, goal, status active|paused|closed, actor_id,
created_at, closed_at)` row is the container Michael starts work in. `session`,
`thesis`, `watchlist`, `peer_group`, `research_question`, `skill_run`, `comparison`,
`company_note`, `saved_search` and `screen` carry a nullable `project_id`. "The
project we started yesterday" is one join. SoR, event-driven like the rest.

Room for more: alerts, portfolios, valuation models, and reading lists are new
tables in the same pattern (SoR, event-driven, `actor_id`, insert-only history).
They are additive and need no change to anything above.

---

## 6. Sequence diagrams

Each note names the transaction boundary.

### 6.1 Skill run with cached pull, projector, ratios

```mermaid
sequenceDiagram
  actor M as Michael
  participant C as Claude
  participant U as USERDATA tools
  participant S as SQLite
  participant P as Projector
  participant D as DuckDB
  participant E as EDGAR

  M->>C: screen company X
  C->>U: session_start(session_id, actor)
  Note over U,S: TX1: event(session_started) + session row
  C->>U: skill_run_start(skill_version_id, inputs)
  Note over U,S: TX2: event(run_started) + skill_run(as_of_event_id = last event)
  C->>U: filing_facts(issuer, form=10-K)
  U->>S: latest successful source_call for params hash within TTL
  U->>D: load_log exists for (raw_sha256, parser_version, fact)?
  alt miss on either
    U->>E: fetch (rate-limited, User-Agent)
    U->>U: write raw/ file (fsync)
    Note over U,S: TX3: raw_payload + source_call + document + event(payload_fetched) + outbox
    P->>S: read outbox
    Note over P,D: TX4 (DuckDB): INSERT fact, statement_line, chunk ON CONFLICT DO NOTHING + load_log
    P->>S: outbox.status = done
  end
  U->>D: SELECT facts
  U-->>C: facts
  C->>U: ratio_compute(issuer, methods, as_of)
  U->>D: read fact_as_of(as_of), price_daily, fx_rate
  Note over U,D: TX5 (DuckDB): INSERT ratio + ratio_input ON CONFLICT DO NOTHING
  U-->>C: ratios with inputs
  C->>U: skill_run_finish(run_id, status, report, files)
  Note over U,S: TX6: blob + report_file + skill_report + skill_run.status + event(run_finished)
  C-->>M: report
```

### 6.2 Michael defines an own concept, publishes it, derives facts

```mermaid
sequenceDiagram
  actor M as Michael
  participant C as Claude
  participant U as USERDATA tools
  participant S as SQLite
  participant A as Arelle CLI
  participant P as Projector
  participant D as DuckDB

  M->>C: mt:AdjustedEbitda = OperatingIncomeLoss + mt:OneOffCosts
  C->>U: taxonomy_draft(mt)
  Note over U,S: TX1: taxonomy_version(status=draft) + event
  C->>U: concept_define(draft_id, qname, type, period, balance, definition)
  Note over U,S: TX2: concept (if new) + concept_version + event
  C->>U: mapping_set(draft_id, target, inputs[weights, signs, period_rule])
  Note over U,S: TX3: concept_mapping rows + event
  C->>U: taxonomy_validate(draft_id)
  U->>U: export taxonomy/mt-vN.xsd + linkbases from rows (under one file lock)
  U->>A: arelleCmdLine --validate
  A-->>U: report
  Note over U,S: TX4: blob(report) + taxonomy_version.status=validated or stays draft + event
  M->>C: publish
  C->>U: taxonomy_publish(draft_id)
  Note over U,S: TX5: status=published, published_at + event + outbox(derive)
  P->>S: read mapping rows for the published version
  P->>D: read input facts (fact_latest)
  Note over P,D: TX6 (DuckDB): INSERT fact(origin=derived) + fact_input + load_log
  C->>U: fact_compare(issuer, mt:AdjustedEbitda, us-gaap:OperatingIncomeLoss)
  U->>D: one query over fact, both concepts, same periods
  U-->>C: side by side
```

### 6.3 Thesis, claim, research question, answer with evidence

```mermaid
sequenceDiagram
  actor M as Michael
  participant C as Claude
  participant U as USERDATA tools
  participant S as SQLite
  participant D as DuckDB

  M->>C: open a thesis on company X
  C->>U: thesis_open(subject_relation_id, stance, body)
  Note over U,S: TX1: thesis + thesis_version(1) + event(thesis_opened)
  M->>C: claim: one-off costs are one-off, kill if they recur next year
  C->>U: claim_add(thesis_id, kind=structure, statement, kill_criterion)
  Note over U,S: TX2: thesis_claim + event
  C->>U: question_queue(claim_id, "do the latest facts show the one-off costs again?", priority)
  Note over U,S: TX3: research_question(open) + event
  Note over C: next session
  C->>U: question_next()
  U->>S: open questions by priority
  U-->>C: question
  C->>U: question_start(question_id)
  Note over U,S: TX4: status=in_progress + event
  C->>U: filing_facts(...) / semantic_search(...)
  C->>U: step_log(question_id, finding, next_step, run_id or call_id)
  Note over U,S: TX5: research_step(seq=n) + event
  C->>U: question_answer(question_id, answer, evidence=[fact_row_id..., chunk_id...])
  U->>D: verify every referenced fact_row_id / chunk_id exists
  Note over U,S: TX6: research_answer + evidence rows + question.status=answered + claim.status + event
  C-->>M: answer with citations
```

### 6.4 A fact is restated: who cited it

```mermaid
sequenceDiagram
  participant P as Projector
  participant D as DuckDB
  participant U as USERDATA tools
  participant S as SQLite
  participant C as Claude

  P->>D: load new 10-K facts (new accession, same periods, different values)
  Note over P,D: fact_latest now points at the new accession, old rows stay
  P->>D: SELECT fact_input WHERE input_fact_row_id IN (superseded rows)
  Note over P,D: recompute affected derived facts and ratios, new rows, old kept
  P->>S: event(facts_superseded, payload=[old fact_row_ids])
  U->>S: SELECT evidence JOIN thesis_claim WHERE fact_row_id IN (old ids)
  U->>D: SELECT ratio_input WHERE input_row_id IN (old ids)
  U-->>C: claims and ratios touched by the restatement
```

### 6.5 Semantic search with filters

```mermaid
sequenceDiagram
  participant C as Claude
  participant U as USERDATA tools
  participant Em as Embedder
  participant D as DuckDB

  C->>U: semantic_search(query, k, issuer, forms, date_range, sections)
  U->>Em: embed([query])
  U->>D: SELECT chunk_id, score FROM chunk_embedding WHERE filters ORDER BY cosine DESC LIMIT k
  U->>D: JOIN chunk for text and char anchors
  U-->>C: k chunks with issuer, form, date, section, text, score, citation anchors
```

### 6.6 Screen, score, peer group, watchlist, comparison

```mermaid
sequenceDiagram
  actor M as Michael
  participant C as Claude
  participant U as USERDATA tools
  participant S as SQLite
  participant D as DuckDB

  M->>C: run my value screen on the universe as of today
  C->>U: screen_run(screen_version_id, as_of)
  U->>D: read ratio as of as_of for every listing
  Note over U,D: TX1 (DuckDB): INSERT screen_result(passed, score) ON CONFLICT DO NOTHING
  U-->>C: ranked passers with scores
  M->>C: put the top ten on my watchlist, and build a peer group around the best one
  C->>U: watchlist_add(watchlist_id, issuers, reason, run_id)
  Note over U,S: TX2: watchlist_item rows + event(watchlist_items_added)
  C->>U: peer_group_create(name, anchor, members, basis=screen, screen_version_id)
  Note over U,S: TX3: peer_group + peer_group_member + event
  M->>C: compare them on EV/EBITDA and FCF yield
  C->>U: comparison_create(peer_group_id, metrics, as_of)
  Note over U,S: TX4: comparison + event
  U->>D: read ratio for members at as_of
  U-->>C: side-by-side table
  C-->>M: table, saved under the comparison name
```

---

## 7. Transactions and invariants (DDIA ch. 7)

Single user is not single writer: Claude issues parallel tool calls, and
Airflow writes later. Every invariant is a database constraint, not an
application check, because Postgres defaults to read committed and
check-then-insert gets write skew there.

| Invariant | Enforced by |
|---|---|
| One event per (stream, stream_seq) | `UNIQUE(stream, stream_seq)`; writer uses `BEGIN IMMEDIATE` and `MAX+1` |
| An MCP retry does not double-write | `event_id` is client-generated; `INSERT OR IGNORE`, then return the existing result |
| One preference per (scope, key) | PK |
| A ticker belongs to one target at a time, per exchange | trigger on `identifier_assignment` rejecting overlapping `[valid_from, valid_to)` per (scheme, value, exchange); Postgres: `EXCLUDE USING gist` |
| A concept has one version per taxonomy version | `UNIQUE(concept_id, taxonomy_version_id)` |
| Only published taxonomy versions are referenced by facts and mappings | `CHECK` via trigger on insert into `concept_mapping`; projector reads only `status=published` |
| Evidence points at exactly one source | `CHECK ((chunk_id IS NOT NULL) + (fact_row_id IS NOT NULL) + (ratio_row_id IS NOT NULL) + (document_id IS NOT NULL) = 1)` |
| A skill version is never edited | no `UPDATE` grant on `skill_version`, `thesis_version`, `concept_version`, `research_step`, `event`, `raw_payload`; triggers raise on `UPDATE`/`DELETE` |
| DuckDB rows are never duplicated | every table has a natural-key PK; loads use `INSERT ... ON CONFLICT DO NOTHING` |
| Cross-store references exist | checked at write; nightly query lists orphans |

Transaction boundaries per tool are the `Note over` lines in §6. Every SQLite
read-modify-write opens with `BEGIN IMMEDIATE` so it cannot hit `SQLITE_BUSY`
mid-transaction. Taxonomy file export runs behind one process-wide lock.

---

## 8. Physical design, now and later (DDIA ch. 3)

### 8.1 SQLite now, Postgres later

`journal_mode=WAL`, `synchronous=FULL` (rule 2 means power loss too, not just a
kill), `foreign_keys=ON`, files `chmod 600` in a `chmod 700` directory.
Postgres gets the same DDL with `jsonb` for JSON columns, `timestamptz` for
dates, `bytea` for blobs, and the gist exclusion constraint for identifiers.
Repositories for this family are written once against SQL that both accept.

### 8.2 DuckDB now, ClickHouse later

DuckDB has no declared sort key; the loader inserts in key order and zone maps
do the rest. ClickHouse needs the table engine chosen now, because `ORDER BY`
cannot change without a rebuild.

| Table | Natural key = DuckDB PK | ClickHouse engine | ORDER BY | PARTITION BY | Version column |
|---|---|---|---|---|---|
| `fact` | fact_row_id (hash of §5.3 key) | MergeTree (append-only: restatements are new rows) | issuer_id, concept_id, period_end, known_at | toYear(period_end) | none |
| `fact_input` | fact_row_id, input_fact_row_id | MergeTree | fact_row_id | none | none |
| `statement_line` | line_row_id | ReplacingMergeTree | accession, statement, line_no | toYear(filed) | code_version |
| `chunk` | chunk_id | MergeTree | document_id, ordinal | toYear(filed_on) | none |
| `chunk_embedding` | chunk_id, model, chunker_version | MergeTree + vector similarity index (HNSW) | issuer_id, document_id, chunk_id | none | none |
| `price_daily` | price_row_id = sha256(listing_id, trade_date, source, raw_sha256); `price_latest` view picks newest known_at | MergeTree (revisions are new rows) | listing_id, trade_date, known_at | toYYYYMM(trade_date) | none |
| `fx_rate` | base, quote, rate_date, raw_sha256; `fx_rate_latest` view | MergeTree | base, quote, rate_date, known_at | toYear(rate_date) | none |
| `ratio` | ratio_row_id | MergeTree | issuer_id, ratio_name, as_of | toYear(as_of) | none |
| `ratio_input` | ratio_row_id, input_kind, input_row_id | MergeTree | ratio_row_id | none | none |
| `screen_result` | screen_version_id, listing_id, as_of | ReplacingMergeTree | screen_version_id, as_of, listing_id | toYear(as_of) | code_version |
| `load_log` | load_batch_id | MergeTree | input_ref, code_version | none | none |

ReplacingMergeTree deduplicates at merge time, so readers use `FINAL` or
`argMax`. Rows the design never updates use plain MergeTree.

Repositories are split by family: OLTP repos (SQLite / Postgres) and OLAP repos
(DuckDB / ClickHouse). Dialect differences inside a family are small; across
families they are not, so no single `execute(sql)` interface pretends
otherwise. SQLGlot (MIT) transpiles where it helps.

Later tools and the single DuckDB writer: the MCP server's projector is the only
writer to `analytics.duckdb`. dbt writes to its own file or schema; Superset and
notebooks open the file `read_only`. On ClickHouse this constraint disappears.

### 8.3 Vector search

v1: `chunk_embedding.vector` as `FLOAT[384]`, `array_cosine_similarity`, brute
force with filters pushed down. ~1 s over 900 k rows. No index, nothing to
persist, rule 2 holds. Later: ClickHouse vector similarity index. The
`VectorStore` interface is `upsert(rows)`, `search(vector, k, filters)`, and the
filter columns are the denormalised ones in §5.5.

---

## 9. Evolution (DDIA ch. 4)

1. **Additive only.** New columns are nullable or defaulted. Removal is
   two-step: stop writing, drop a version later.
2. **Every JSON column has a schema id** next to it (`*_schema = name@version`),
   with JSON Schema files in `schemas/`. Readers handle version N and N−1; CI
   tests both. Schema-on-read still needs the writer's schema (Avro's lesson).
3. **Events are versioned** (`type_version`) and upcast on read. Replay of the
   whole log into fresh projections is a CI test.
4. **Long tables absorb new concepts.** A new ratio, line item or concept is a
   row, not a column.
5. **Versioned migrations** per store: `migrations/oltp/0001_*.sql` and
   `migrations/olap/0001_*.sql`, with a `schema_migration` table in each.
6. **Names are dbt-ready.** These tables are the `core` layer; dbt marts build
   on top. Unity Catalog name: `userdata.core.<table>`.
7. **Code version on every derived row** so a parser or method fix reloads only
   what it touched.

---

## 10. Decisions for Michael

1. **Data directory**: `~/Slop/userdata-data/` (recommended) or inside the repo.
2. **Embedding model**: `all-MiniLM-L6-v2` (Apache-2.0, fast) or
   `bge-small-en-v1.5` (MIT, better retrieval). Both 384 dims.
3. **MCP framework**: FastMCP 4 (Apache-2.0) or the official SDK's FastMCP
   (MIT). Your Yahoo fork uses the official SDK.
4. **Own taxonomy prefix**: `mt`.
5. **Base taxonomies to load**: us-gaap and dei for the years you follow
   (2023–2025), or only the concepts that appear in your filings.
6. **`unidecode` in the edgartools fork**: replace with `anyascii` (ISC) now.
7. **Chunk text in DuckDB, not SQLite**: agree, or keep text next to tags.
