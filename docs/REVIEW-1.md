# REVIEW-1 — USERDATA SDD Draft 1, data architecture

Reviewer stance: DDIA (Kleppmann, 1st ed. chapter numbering). Reviewed: `docs/SDD.md`
Draft 1, 2026-10-30, whole file. Nothing in the SDD was changed.

## (a) Verdict

The draft has the right instincts (OLTP/OLAP split, long fact tables, immutable
content-addressed raw, engine interfaces) but it never decides, table by table,
which data is the **system of record** and which is **derived** (DDIA Part III
intro, ch. 11-12). The result is dual writes across SQLite, DuckDB and `raw/` with no
atomicity, mutable current-state tables where history is the product, and DuckDB rows
with no identity, so the core use case (tag a reported line with an own concept and
compare it to reported facts) cannot be expressed as drawn. Fix findings 1-5 before
any code: each one gets much more expensive once real data is in.

## (b) Findings, most damaging first

### 1. DuckDB rows have no identity or natural key, yet four features depend on one
- **What is wrong.** `statement_line`, `xbrl_fact`, `price_daily`, `ratio` and
  `chunk_embedding` have no PK and no declared unique key. But `tagging.target_kind`
  allows `statement_line | fact`, which needs a `target_id`. `custom_fact.basis` is
  supposed to say "which source facts / statement lines it came from", which needs row
  ids. §8 says "every step is idempotent on its key", which needs a key. And a later
  ClickHouse `ORDER BY` / `ReplacingMergeTree` dedup is defined *by* that key. Today a
  TTL-expired re-fetch in §7.1 runs `INSERT statement_line rows` again, so the rows
  duplicate.
- **DDIA.** ch. 11 "Idempotence" and exactly-once via idempotent writes; ch. 3 sort keys
  and how column stores order data; ch. 2 the relational model needs stable references
  to express relationships.
- **Rework cost.** High, and it grows with the data. Once taggings and custom facts
  exist, adding ids afterwards means a backfill plus a fuzzy re-match of every
  `basis`/`target_id` reference. Duplicates already loaded have to be found by a guessed
  key. The ClickHouse `ORDER BY` cannot be changed without rebuilding the table.
- **Fix.** Give every analytical table a declared natural key and a deterministic
  surrogate. Examples: `xbrl_fact` = (accession, concept_qname, context hash: entity +
  period + canonical `dimensions_key`, unit); `statement_line` = (listing/entity,
  source, statement, period_type, period_end, line_item, raw_sha256);
  `price_daily` = (listing_id, trade_date, source). Write with
  `INSERT ... ON CONFLICT DO NOTHING/UPDATE` now, which becomes ReplacingMergeTree
  `ORDER BY <same key>` later. Store a `row_id = sha256(natural key)` so references
  survive the engine move.

### 2. No system-of-record / derived split: dual writes, non-atomic cache, and a false "rebuild from raw" claim
- **What is wrong.** One request writes the `raw/` file, then SQLite (`raw_payload`,
  `source_call`), then DuckDB (`statement_line`) (§7.1, §8). Nothing makes that atomic.
  A crash after the SQLite commit and before the DuckDB insert leaves `source_call`
  saying "cached and fresh" while DuckDB holds nothing, so every later call is a cache
  hit that returns an empty result until the TTL runs out. That breaks hard rule 2.
  Separately, §6.1 says "every derived table can be rebuilt from [raw]". That is false
  for `custom_fact`, `tagging`, `preference`, `skill_*`, `concept*`, and for `ratio`,
  which Claude pushes through `ratio_put` with LLM-chosen inputs rather than computing
  it with deterministic code. Those tables are systems of record and need backup and
  history, not rebuilds.
- **DDIA.** ch. 11 "Keeping Systems in Sync" (dual writes: race conditions and partial
  failure); ch. 7 atomicity; ch. 9 atomic commit / 2PC, which you should avoid by design
  rather than by luck; ch. 12 "Unbundling Databases": derived stores are fed from a log
  by idempotent consumers, and the application does not write to each store by hand.
- **Rework cost.** High. The Postgres-to-ClickHouse future is naturally CDC (Postgres is
  the record, ClickHouse is derived). v1 trains every service to write to both stores
  directly, so each service has to be rewritten into a producer and a projector later.
  Lost or inconsistent cache state becomes silent wrong answers.
- **Fix.** Label every table **SoR** or **Derived(from, by code_version)** in §6.3.
  Commit order is raw file, then SQLite SoR rows, then an **outbox/event row in the same
  SQLite transaction**. An idempotent projector loads DuckDB and records
  `load_log(raw_sha256, parser_version, target_table)` **inside the DuckDB transaction**
  that inserts the rows. A cache hit means the `load_log` row exists, not just the
  `source_call` row. Ratios are computed by versioned code from stored facts; Claude
  picks the method, it does not supply the numbers.

### 3. Own-concept facts are split from reported facts, and the concept-to-reported mapping is not modelled at all
- **What is wrong.** Michael's core use case is to define `mt:AdjustedSpinEbitda =
  operating income + separation costs`, tag statement lines with it, and compare the
  result with reported XBRL facts. As drawn:
  - (a) The formula is free prose in `concept.definition`. The derivation function is
    not data.
  - (b) `custom_fact` lives in SQLite (`real`, ISO-text dates, `concept_id`), while
    `xbrl_fact` and `statement_line` live in DuckDB (`DOUBLE`, `DATE`, `concept_qname`,
    `std_concept`). "Same shape on purpose, so the two can be unioned" is not true: the
    key types, date types, value types and columns differ (no `accession` or `decimals`
    on custom; no `fact_id` on reported). §6.3 says `std_concept` is "the join key to
    `custom_fact`", but `custom_fact` has no qname column.
  - (c) `concept_relation` FKs point only at `concept` rows, which are only Michael's
    taxonomy. You cannot draw a calculation arc from `mt:AdjustedSpinEbitda` to
    `us-gaap:OperatingIncomeLoss`.
  - (d) `concept` is mutable. Edit a definition and every earlier `custom_fact` silently
    changes meaning.
  - (e) "Tag a statement line with a concept" is routed through generic `tagging`
    (§7.2 `tagging_put(tag or concept, ...)`), but `tagging` has only `tag_id`, so a
    concept cannot be its subject.
- **DDIA.** ch. 2: the relational model wins when you need joins and references, and
  splitting one fact family across two engines throws that away. ch. 10/12: derived
  data is a pure function of inputs plus code, so store the function (the mapping) as
  data and the outputs as derived. ch. 3: the comparison is an OLAP scan, so it belongs
  where the reported facts are.
- **Rework cost.** High. This is the product. Every comparison query is a cross-engine,
  cast-heavy union. Moving `custom_fact` later means migrating the authoritative,
  hand-made data under the most important queries.
- **Fix.** Keep the *authored* objects in SQLite and version them immutably:
  `concept_version`, plus `concept_mapping(concept_version_id, entity_id NULL,
  input_ref = qname or statement-line key, weight, sign, period_rule)`. Load base
  taxonomies (us-gaap/dei by year) as `taxonomy` + `concept` rows so arcs and mappings
  can reference them. Put **one** long `fact` table in DuckDB with
  `origin = reported | derived | manual`, the same types, and lineage columns
  (`mapping_version_id`, `inputs` row_ids, `code_version`). Hand-typed values are
  `origin=manual` rows from an SoR `manual_fact` in SQLite.

### 4. The skill store keeps a path and a hash: the database is not the source of truth for skills
- **What is wrong.** `skill_version.source_path` + `content_sha256` is a pointer into a
  mutable filesystem. The hash can *detect* that the file changed or disappeared, but it
  cannot *recover* the text that produced a past run, so lineage (§6.3 "a report always
  points at the exact skill text") is not actually kept. Real skills are bundles
  (SKILL.md plus reference files and scripts), and one path cannot hold a bundle.
  `skill_report.artifact_path` repeats the same mistake for outputs. The inconsistency
  shows: the taxonomy is DB-to-file (§7.2 regenerates `.xsd` from rows, which is right),
  while skills are file-to-DB.
- **DDIA.** ch. 11 "Immutable events" / ch. 12: the system of record holds the
  authoritative bytes, and files on disk are a derived materialised view. ch. 4: props
  are a document with an evolving schema.
- **Rework cost.** Medium now, unbounded later. Every run recorded against a path whose
  file was later edited has lost its provenance for good.
- **Fix.** `skill_blob(sha256 PK, bytes BLOB, media_type)` content-addressed in the DB;
  `skill_version(skill_version_id, skill_id, version, parent_version_id,
  manifest_sha256, props JSON, props_schema_version, created_by, created_at)`
  insert-only; `skill_version_file(skill_version_id, rel_path, blob_sha256)`.
  `skill.current_version_id` is a derived pointer (or a view over the event log).
  "Install to `~/.claude/skills`" becomes an export step. Store report artifacts as
  blobs the same way and keep paths only as export hints.

### 5. `session_event` is a log table, not event sourcing, and the state that matters is mutable
- **What is wrong.** The only append-only table holds notes and tool calls. The state
  whose history matters (preferences, which the SDD itself calls "identity
  adjustments", plus tags, concepts and skill versions) is updated in place.
  `session.ended_at`/`title` and `skill_run` are `UPDATE`d (§7.1), so "current state is
  derived from events" (§6.3, `session` row) is false. Missing pieces:
  - no client-generated `event_id` / idempotency key, and MCP clients retry;
  - no `event_type` + `event_version` (an upcasting rule);
  - no `actor` (Michael, Claude, a skill, later Airflow);
  - no causation/correlation id;
  - no stream id other than session;
  - no defined projections and no replay procedure;
  - `seq` is an SQLite rowid, and the Postgres move needs it as an explicit identity /
    sequence.

  Snapshots are not needed at this volume; say so explicitly.
- **DDIA.** ch. 11 "Event Sourcing", "Deriving current state from the event log",
  "Commands and events", "State, Streams, and Immutability" ("the log is the truth; the
  database is a cache of a subset of the log").
- **Rework cost.** Medium. History not captured now cannot be backfilled. A skill run
  cannot be reproduced because the preferences in force at the time are gone.
- **Fix.** One `event` table as the SoR for user-authored state: `(event_id UUID PK,
  stream, stream_seq, type, type_version, payload JSON, actor, causation_id,
  recorded_at, UNIQUE(stream, stream_seq))`. Make `preference`, `tag`, `concept_version`
  and `skill.current_version_id` projections, rebuilt by a tested replay. `skill_run`
  stores `as_of_event_id`, so "what did Claude know about Michael when it wrote this
  report" is a query. A simpler version that is still acceptable for preferences:
  `preference_change` insert-only plus a `preference_current` view.

### 6. Identity is modelled at the wrong grain: issuer, security and listing are conflated
- **What is wrong.** `entity` + `identifier(scheme, value, exchange, valid_from,
  valid_to)` puts CIK/LEI (issuer level), ISIN/CUSIP/share-class FIGI (security level)
  and ticker/exchange FIGI (listing level) on one entity. `price_daily` is keyed by
  `entity_id`, but prices belong to a listing (GOOG vs GOOGL; when-issued `XXXX WI` vs
  regular-way, which is central to spin-off trading). Also:
  - `identifier` has no PK and no uniqueness rule;
  - nothing stops overlapping intervals or a ticker being given to two entities at once;
  - the meaning of a NULL `valid_to` is undefined;
  - "find entity by (scheme, value)" ignores time, so a reused ticker resolves to the
    wrong company;
  - `entity_id` is a random UUID minted at resolution time, so resolving first by
    ticker and later by CIK can create two entities for one company, and there is no
    merge/alias table.
- **DDIA.** ch. 2 normalisation and why ids are separated from human-meaningful values
  ("Many-to-One and Many-to-Many"). On time: DDIA's own framing is ch. 11 "Reasoning
  About Time" (event time vs processing time). Bitemporality as a named pattern is
  outside DDIA (Snodgrass/Fowler); UNSURE whether you would call it a DDIA
  recommendation, but it follows from ch. 11's event-time/processing-time split.
- **Bitemporal or not.** For identifiers, valid time plus `source_call_id` /
  `recorded_at` (knowledge time) is enough. Full bitemporal queries are not needed. For
  facts, knowledge time is mandatory (finding 7).
- **Rework cost.** High. Every price, ratio and chunk filter keyed by `entity_id` has to
  be re-keyed when listings arrive.
- **Fix.** `issuer` → `security` → `listing` tables, with identifiers attached at their
  real level. `identifier_assignment(scheme, value, level, target_id, valid_from,
  valid_to NOT NULL DEFAULT '9999-12-31', source_call_id, recorded_at)`. Enforce "no
  overlap per (scheme, value)" with a trigger in SQLite, and later with Postgres
  `EXCLUDE USING gist (scheme WITH =, value WITH =, daterange(valid_from, valid_to)
  WITH &&)`. Add `entity_alias(merged_id → survivor_id)`. Make issuer ids deterministic
  where a CIK exists.

### 7. Restatements and point-in-time: no "as reported when" dimension on facts, statements or ratios
- **What is wrong.** The FY2024 revenue in the FY2024 10-K and the restated FY2024
  comparative in the FY2025 10-K are two facts. `xbrl_fact` keeps `accession`, which is
  good, but there is no rule for "latest" versus "as first reported". `statement_line`
  (Yahoo) has no accession and no knowledge time, so a TTL re-fetch either duplicates
  rows (finding 1) or overwrites history. `ratio.as_of` is undefined: is it the price
  date, or the date the inputs were public? A screener built on this has look-ahead
  bias. For spin-offs, Form 10 **pro forma / carve-out** statements are a different
  basis from post-spin as-reported numbers, and there is no `basis` column for that.
- **DDIA.** ch. 11 "Reasoning About Time" (event time vs processing time) and
  "immutable events"; ch. 10 reproducible derived outputs.
- **Rework cost.** High for any backtest or screen history. It cannot be reconstructed
  if the overwritten payloads were not kept (they are kept in `raw/`, so it is
  rebuildable *if* finding 1 is fixed).
- **Fix.** Add `known_at` (filing `acceptance_datetime`, or `fetched_at` for Yahoo) and
  `statement_basis = as_reported | restated | pro_forma | carve_out` to `fact` and
  `statement_line`. Define the views `fact_latest` and `fact_as_of(date)`. Define
  `ratio.as_of` as the knowledge cut-off and store `price_date` separately.

### 8. Missing spin-off domain entities
The use cases need these, and the ERD lacks them:
- `entity_relation(from, to, kind = parent | spun_off_from | predecessor | subsidiary |
  acquirer, effective_date, source)`. This is the core graph for spin analysis, and
  ch. 2's graph-as-edge-table already used for concepts fits it.
- `corporate_action(kind = spin_distribution | split | dividend | ticker_change | merger,
  ratio, declaration/record/ex/distribution dates, when-issued window,
  cost-basis allocation per Form 8937)`. Without it `adj_close` cannot be checked and
  the spin itself is not a record.
- `fiscal_period(entity, fy, fp, start, end)`. `period_type annual|quarterly|ttm` plus
  `period_end` is ambiguous for non-December year ends and 52/53-week years. Use DEI
  `DocumentFiscalPeriodFocus`.
- `unit` / currency plus `fx_rate`. `unit` is free text in two tables and `currency` in
  a third.
- `screen` (definition, versioned) and `screen_result(run, listing, as_of, pass, score)`.
  This is "store screener ratios" as an actual object. Also `analysis` / `thesis` /
  `watchlist`: the thing Michael actually produces, which today only exists inside the
  `skill_report.body` JSON.
- `actor` on every SoR write (Michael vs Claude vs skill vs scheduler). §5 says
  "Michael owns the meaning, Claude does the mechanical work", but the schema cannot
  tell them apart.
- `dq_issue` / `override`: a correction layered over a source value, never an edit of
  it.
- On `chunk`: `char_start/char_end` or page anchors for citation, plus the
  chunker/parser version.

**DDIA.** ch. 2 (model the many-to-many relationships explicitly); ch. 12 "Designing for
auditability". **Rework cost.** Medium per table, but `listing` and `fiscal_period`
re-key existing tables. **Fix.** Add these now as empty tables with keys. Additive
later is fine for the rest.

### 9. The engine abstraction is drawn at the wrong level, and the ClickHouse target has no table-engine plan
- **What is wrong.**
  - `RelationalEngine.execute(sql)` with "all SQL lives in repositories" means the SQL
    dialect leaks. SQLite `ON CONFLICT`, JSON functions, `WITH RECURSIVE`, and `UPDATE`
    all differ in ClickHouse. "Swapping DuckDB for ClickHouse is a config change plus a
    new engine class" (§4) is false: every analytical repository changes. "Same files
    target Postgres and ClickHouse with dialect folders" (§6.4) means different files.
  - There is no per-table ClickHouse design. Append-only tables (prices, reported facts)
    need `MergeTree ORDER BY (listing_id, trade_date)` /
    `ORDER BY (entity_id, concept_qname, period_end, accession)` with monthly or yearly
    `PARTITION BY`. Revisable rows (`statement_line`, `ratio`, derived `fact`) need
    `ReplacingMergeTree(version_col)` with an `ORDER BY` equal to the natural key, and
    reads via `FINAL` or `argMax`, because ClickHouse has no cheap `UPDATE` (mutations
    are asynchronous rewrites).
  - `json dimensions` cannot sit in a sort key, so a canonical `dimensions_key` string
    or hash column is needed.
  - Recursive CTEs for `concept_relation` in ClickHouse: UNSURE about the version
    support. Keep graph walks on the OLTP side (Postgres), where they belong.
  - DuckDB has no declarable sort key, so "Sorted by (entity_id, trade_date)" (§6.3,
    `price_daily` row) only holds if the loader inserts in that order. Zone maps do the
    rest.
- **DDIA.** ch. 3 "Column-Oriented Storage", "Sort Order in Column Storage"; ch. 3
  LSM-style merge (ReplacingMergeTree is a merge-time dedup, so readers see duplicates
  until a merge runs).
- **Rework cost.** Medium to high. It surfaces as a rewrite of every analytical
  repository plus new duplicate-reading bugs.
- **Fix.** Split repositories by engine family (OLTP repos on SQLite/Postgres, OLAP repos
  on DuckDB/ClickHouse). Optionally write the SQL once and transpile it with SQLGlot
  (MIT). Add a §6.6 "target physical design" table: per table, the ClickHouse engine,
  ORDER BY, PARTITION BY and version column, and the Postgres PK/indexes.

### 10. Transaction boundaries and invariants are unstated, and they rely on SQLite's accidental serializability
- **What is wrong.**
  - "Single user" is not "single writer": Claude issues parallel tool calls, and later
    Airflow writes too. Check-then-insert invariants (qname not taken, ticker not
    assigned, preference exists) are only safe because SQLite serialises writers.
    Postgres defaults to READ COMMITTED, so the same code gets write skew after the move.
  - Missing uniqueness constraints: `preference` (no PK; should be
    `UNIQUE(user_id, scope, key)`), `identifier`, `concept(taxonomy_id, qname)`,
    `concept_label`, `concept_relation`, `document(accession)`, `tag(namespace, name)`.
  - §7.2 commits the `concept` row, *then* regenerates the `.xsd`, *then* validates.
    Arelle failure leaves an invalid concept committed. Two concurrent `concept_define`
    calls race on the same `taxonomy/` files. `arelle_status` sits on `taxonomy`, not on
    the version that was validated.
  - `skill_run_finish` (UPDATE run, INSERT report, INSERT event) is not stated to be one
    transaction.
  - Deferred SQLite transactions that read and then write can fail with `SQLITE_BUSY`
    under WAL.
- **DDIA.** ch. 7 "Write Skew and Phantoms", "Materializing conflicts", weak isolation
  defaults; ch. 7 on why constraints beat application checks.
- **Rework cost.** Medium. Concurrency bugs appear only after the Postgres move, which is
  the worst time to find them.
- **Fix.** Declare every invariant as a DB constraint. Use `BEGIN IMMEDIATE` for every
  read-modify-write in SQLite. Write down the transaction boundary for each tool in §7.
  Make a taxonomy change a new `taxonomy_version`: draft, then validate, then publish,
  with only published versions referenceable. Serialise file regeneration behind one
  lock.

### 11. Polymorphic `tagging.target_kind + target_id`
- **What is wrong.** No FK is possible. Orphans appear on delete or re-ingest. The
  `target_kind` enum drifts. Every "tags on X" query is a `CASE`/`UNION` per kind. Two of
  the four kinds point into DuckDB rows that have no ids (finding 1). "Fewer tables, same
  queries" (§6.3) is boilerplate: the queries are not the same, and integrity is lost.
  The ERD draws `tagging }o--|| document` **and** `}o--|| chunk`, which says every
  tagging has exactly one of each. That is wrong. The `statement_line` and `fact`
  targets are not drawn at all.
- **DDIA.** ch. 2: this is the relational model fighting a heterogeneous many-to-many.
  DDIA's answer is either explicit relational join tables or a property graph
  (vertices + labelled edges), and polymorphic ids are neither.
- **Rework cost.** Medium. Postgres cannot add the FK later without changing the
  structure.
- **Fix.** Either one join table per target kind (`document_tag`, `chunk_tag`,
  `line_tag`, `fact_tag`, each with a real FK or a natural-key reference), or a
  supertype `taggable(taggable_id PK, kind)` that every target row registers in. Keep
  concept-to-line mapping out of tagging (finding 3): it has semantics (weight, sign,
  period) that a tag does not.

### 12. Vector search cannot filter: metadata lives in the other database
- **What is wrong.** §7.3 filters by entity, form, section and date, but
  `chunk_embedding` holds only `chunk_id`, and the metadata is in SQLite. You either
  scan everything and post-filter (fewer than k results, wrong ranking) or join across
  engines on every query. HNSW in ClickHouse later has the same pre-filter/post-filter
  problem. The table also has no chunker version, and no unique key on
  `(chunk_id, model)`. Hard rule 2 "including vector search results": DuckDB `vss` HNSW
  persistence is behind an experimental flag (UNSURE of current status). Brute-force
  cosine has no index to persist, so it is the safer v1 choice.
- **DDIA.** ch. 3: analytical and index stores denormalise what the query filters on.
  ch. 12: a derived index carries whatever its readers need.
- **Rework cost.** Low to medium.
- **Fix.** Denormalise `entity_id/listing_id, document_id, form, filed_at, section,
  chunker_version` into `chunk_embedding`. Key it `UNIQUE(chunk_id, model,
  chunker_version)`.

### 13. Cache: content addressing is right, but the details are wrong or missing
- **What is wrong.**
  - `source_call ||--|| raw_payload` contradicts content addressing. It must be
    `}o--||` (many calls, one payload), and `o|` for failed calls with no body.
  - Params canonicalisation (key order, defaults, types, case of tickers) is unspecified,
    so `params_sha256` will miss.
  - There is no rule for caching errors (429, 404).
  - Is history kept, meaning several `source_call` rows per params hash? It should be:
    two payloads for the same params is how you see a Yahoo revision. If so, the lookup
    needs "latest successful".
  - Lineage grain: derived rows carry `call_id` (the fetch) rather than `raw_sha256` +
    `parser_version` (the content and the code). Nothing records the edgartools-fork
    version or parser version that produced a row, so "rebuild from raw" cannot be
    selective.
  - `raw/` sits on one local disk, so hard rule 2 does not cover disk loss. A B2 copy via
    rclone is the obvious fix (outside DDIA's data-model scope; ch. 5 replication in
    spirit).
- **DDIA.** ch. 10 "Philosophy of batch process outputs" (immutable inputs plus versioned
  code means reproducible outputs, and you can rerun after a bug); ch. 12 auditability.
- **Rework cost.** Low now, high later. Without `code_version`, a parser bug means
  rebuilding everything because you cannot tell which rows are affected.
- **Fix.** Fix the cardinality. Specify the canonical-params function in code and test
  it. Add `error_class` and `negative_ttl`. Put `(raw_sha256, code_version)` on every
  derived row, or on a `load_batch` row that each derived row references.

### 14. JSON columns are schema-on-read with no writer schema id
- **What is wrong.** Rule 2 in §6.4 ("new keys need no migration") treats JSON as free.
  Readers cannot tell which shape they are holding: `preference.value`,
  `skill_version.props`, `session_event.payload`, `ratio.inputs`, `skill_report.body`.
  `ratio.inputs` "every number used, with its source row" points at rows that have no
  ids (finding 1).
- **DDIA.** ch. 4: schema-on-read still needs the writer's schema (Avro writer/reader
  schema resolution), and forward/backward compatibility rules are per field. ch. 2
  "Schema flexibility in the document model".
- **Rework cost.** Low to medium. It shows up as defensive parsing code everywhere.
- **Fix.** Pair every JSON column with `*_schema` (name@version) and keep JSON Schema
  files in the repo. CI checks the reader handles N and N-1. Move `ratio.inputs` to a
  child table `ratio_input(ratio_row_id, input_row_id, role)`.

### 15. §6.3 rationales: some are convincing, several are boilerplate or wrong
- **Convincing:** `concept_relation` (edge table + recursive CTE), `price_daily`,
  `xbrl_fact` (long, JSON dims), `source_call`/`raw_payload` as an idea, `skill_report`
  as a document.
- **Boilerplate or wrong:**
  - `user_profile`: "multi-user later costs nothing", but only `preference` and
    `session` carry `user_id`. Tags, concepts, facts and skills do not, so multi-user
    would cost a lot. Either commit to `owner_id` everywhere or drop the claim.
  - `session`: "current state is derived from events" is false (finding 5).
  - `entity`: cardinality "—".
  - `tag`/`tagging`: "same queries" is false (finding 11).
  - `custom_fact`: "same shape as `xbrl_fact`" is false (finding 3).
  - `statement_line`: "`std_concept` is the join key to `custom_fact`" — no such column
    exists. And standardised by whom, at which version?
  - `ratio`: `method_version` with no key to pick the current method, and `as_of`
    undefined (finding 7).
  - `identifier`: "valid_from/to is the minimum temporal model" — true, but there is no
    constraint behind it.
- **Across the table:** "Cardinality" gives relationship multiplicity, never **row
  volumes**. Apart from "a few hundred thousand vectors" there are no numbers: filings
  per year, chunks per filing, facts per 10-K (roughly 1-3k), price rows. So the SQLite
  vs DuckDB placement of `chunk` (all filing text, likely GBs) is unjustified. DDIA ch. 1
  "Describing Load" asks for exactly those numbers.

### 16. The ERD fails to render, and its cardinalities are wrong in places
- **Syntax (verified with the mermaid@11.4.1 parser):** the main `erDiagram` block
  **fails**.
  - `concept ||--o{ concept_relation : to`: `to` is a reserved token in the
    word-cardinality grammar ("Expecting ... got 'IDENTIFYING'"). Rename the label to
    e.g. `to_concept`.
  - `text run_id PK_FK` is not a valid key. Use `text run_id PK, FK`.

  With both changes the diagram parses. The DuckDB `erDiagram` parses. All C4,
  flowchart, sequence and class blocks parse. Comments containing `<id>` (`preference`)
  parse; UNSURE whether GitHub's renderer strips `<id>` as HTML. Use `{id}` to be safe.
  GitHub's bundled Mermaid version may differ from 11.4.1 (UNSURE).
- **Cardinality errors:**
  - `tagging }o--|| document` and `}o--|| chunk` (finding 11).
  - `source_call ||--|| raw_payload` should be `}o--o|` (finding 13).
  - `session ||--o{ skill_run` forces a session on every run; scheduled runs later have
    none, so use `o|`.
  - `entity ||--o{ document` forces an entity on `source=user` documents.
- **Missing lines:**
  - `document.raw_sha256` → `raw_payload`;
  - `skill_run` → `tagging` (`run_id` FK exists but is not drawn);
  - every cross-database reference (`entity` → `price_daily`/`statement_line`/
    `xbrl_fact`/`ratio`, `chunk` → `chunk_embedding`, `skill_run` → `ratio`). The
    DuckDB diagram has no relationships, so a reader cannot see the cross-store
    coupling, which is the riskiest part of the design. Draw it as one diagram with
    store boundaries in comments, or as a second diagram of cross-store keys.
- **Missing PKs:** `preference`, `identifier`, `concept_relation` and `concept_label`
  have no PK. No DuckDB table has one.

### 17. Smaller items
- `synchronous=NORMAL` in WAL mode survives a process kill (hard rule 2 as worded) but
  can lose the last commits on power loss or an OS crash. Say which one you mean.
  `chmod 700` on `store.db` is a directory mode applied to a file; use 600 for files.
- Random UUIDv4 keys spread B-tree inserts (ch. 3) and compress badly in column stores.
  Use UUIDv7 or deterministic hashes of natural keys.
- ISO-text dates in SQLite: fix UTC with a `Z` suffix and one format, enforced by
  `CHECK`. Otherwise the cast to DuckDB `DATE`/`TIMESTAMP` in cross-store joins fails or
  shifts by timezone.
- Later tools vs the single DuckDB writer: §2 says Airflow, dbt and Superset "talk to the
  stores directly", but the MCP server holds the only DuckDB write handle (§6.5), so
  dbt-duckdb cannot write while the server runs. That is another reason for finding 2:
  derived stores fed by one projector, with dbt writing to its own file or schema and
  readers using `read_only`.

## (c) What the draft gets right: keep these

1. OLTP/OLAP split by workload, with the reasoning written down (ch. 3). The split is
   right; the problem is only which side certain tables sit on.
2. Long/narrow fact tables for facts, lines, prices and ratios, with open XBRL dimensions
   as data rather than columns (ch. 2/3).
3. Immutable, content-addressed raw payloads as the base for all external data (ch.
   10/11). This is what makes findings 1, 7 and 13 fixable without re-fetching.
4. Taxonomy as an edge table walked by recursive CTE, with `.xsd`/linkbases *generated
   from* the DB and validated by Arelle (DB as SoR, files derived). Apply the same rule
   to skills.
5. `skill_run` as the lineage anchor, `method_version` on ratios, and the `model` column
   on embeddings (versioned derivations, ch. 10).
6. Engine choice behind interfaces and in config. The direction is right; move the seam
   down to the repository family (finding 9).
7. Additive-only migrations with a two-step removal, and a `schema_migration` table per
   store (ch. 4).
8. Avoiding FK dependence in the analytical store from day one, because ClickHouse has
   none. Keep it, but replace "service layer owns integrity" with natural keys, idempotent
   loads and a load log (findings 1-2).

## (d) Michael's direction during the review (for the SDD author to apply)

Michael, mid-review, said two things:

1. **Simplify the SDD.** It is mostly for him. Keep **use cases, the ERD (with per-table
   rationale), and the sequence diagrams**. Drop the C4 levels 1-3, the class diagram and
   the activity diagram for now; they can come back when there is code. Keep the
   rationale *argued*: each table says what it is for, how it is read, roughly how many
   rows, and why it is normalised or not. One line of reason is not enough, and
   boilerplate gets cut (finding 15).
2. **Add a thesis manager and a research manager for the thesis.** This also fills the
   "analysis/report objects" gap in finding 8. Proposed relational design and its
   reasoning:

| Table | What it holds | Access pattern | Rows (est.) | Shape and why |
|---|---|---|---|---|
| `thesis` | one investment idea: subject (issuer, or the `entity_relation` row for a parent/spinco pair), stance, status `draft / active / closed / invalidated`, opened/closed dates | list active; by subject | tens | Relational, SoR in SQLite. A thesis is an entity other rows point at, so it needs a stable id and FKs, not a JSON blob in `skill_report`. |
| `thesis_version` | immutable text of the thesis at a point in time, `created_by` actor | latest per thesis; diff two versions | hundreds | Insert-only, same pattern as `skill_version` (finding 4). "What did I believe on date X" is the point of a thesis, so history is the record (ch. 11). |
| `thesis_claim` | one testable statement: kind `catalyst / valuation / risk / structure`, the **kill criterion** (what would prove it wrong), status `open / supported / refuted` | claims of a thesis; open claims across all theses | hundreds | Relational 1:N from thesis. Claims are what research works against, so they must be rows, not paragraphs. |
| `evidence` | one link from a claim to a source, with role `supports / contradicts / context` and a note | evidence for a claim; **reverse: which claims cite this fact/chunk** | thousands | M:N between claim and sources. Use **one FK column per source kind** (`chunk_id`, `fact_row_id`, `ratio_row_id`, `document_id`) with `CHECK (exactly one NOT NULL)` (an exclusive arc), not `target_kind + target_id` (finding 11). The reverse lookup is the reason: when a fact is restated (finding 7), you must find every claim that cited it, and that needs real references. |
| `research_question` | the research manager's unit of work: question, thesis/claim it serves, priority, status `open / in_progress / answered / dropped`, assignee actor (Michael or Claude) | open queue by priority; by thesis | hundreds | Relational, SoR. A queue Claude can pick from in every session without being re-told. |
| `research_step` | append-only log of what was done for a question: the `skill_run`, `source_call` or search it used, the finding, the next step | steps of a question in order | thousands | Event log keyed by question (finding 5 pattern, `event` stream = question id). The trail is the product, so it is never updated in place. |
| `research_answer` | the answer and the `evidence` rows it created; closes the question | by question | hundreds | 1:1 with a closed question. Kept separate so answering is one transaction: insert the answer + evidence + status event together (finding 10). |

Why relational and not document here (ch. 2): theses, claims, questions and evidence
are densely cross-referenced (many-to-many claim-source links, reverse lookups from
facts to claims, a queue filtered by status across theses), and DDIA's rule is that
many-to-many relationships and joins favour the relational model. Only the free text
(the thesis body, the note, the answer) is document-shaped, and it sits in text columns.
All of it is small OLTP data, so it goes in SQLite now and Postgres later. None of it
belongs in DuckDB.

New use cases for the simplified SDD: *open / revise / close a thesis*, *add a claim with
a kill criterion*, *queue a research question*, *work a question (log steps)*, *answer a
question with evidence*, *see which theses a restated fact affects*. Each needs one
sequence diagram.
