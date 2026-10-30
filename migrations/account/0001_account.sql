-- Account store (SQLite). events is the append-only history.

create table projects (
    project_id text primary key,
    project_name text not null unique,
    goal_text text,
    created_at text not null
);

create table sessions (
    session_id text primary key,
    project_id text references projects (project_id),
    session_title text,
    started_at text not null,
    ended_at text
);

create table events (
    event_id text primary key,
    session_id text references sessions (session_id),
    project_id text references projects (project_id),
    event_type text not null,
    actor_name text not null,
    event_details text not null check (json_valid(event_details)),
    recorded_at text not null
);

create index events_by_session on events (session_id, recorded_at);

create trigger events_are_never_updated before update on events
begin
    select raise(abort, 'events are append-only') as refusal;
end;

create trigger events_are_never_deleted before delete on events
begin
    select raise(abort, 'events are append-only') as refusal;
end;

create table preferences (
    preference_key text primary key,
    preference_value text not null check (json_valid(preference_value)),
    updated_at text not null
);

create table lists (
    list_name text primary key,
    project_id text references projects (project_id),
    list_type text not null check (list_type in ('watchlist', 'peer_group')),
    purpose_text text,
    created_at text not null
);

create table list_members (
    list_name text not null references lists (list_name),
    ticker text not null,
    reason_text text,
    added_at text not null,
    removed_at text,
    primary key (list_name, ticker, added_at)
);

create unique index list_members_current
on list_members (list_name, ticker)
where removed_at is null;

create table notes (
    note_id text primary key,
    project_id text references projects (project_id),
    ticker text,
    note_text text not null,
    created_at text not null
);

create table taggings (
    tag_name text not null,
    target_type text not null check (
        target_type in ('filing', 'fact', 'ticker', 'note')
    ),
    target_id text not null,
    note_text text,
    tagged_at text not null,
    primary key (tag_name, target_type, target_id)
);

create table skills (
    skill_name text not null,
    skill_text text not null,
    skill_settings text not null check (json_valid(skill_settings)),
    version_number integer not null,
    created_at text not null,
    primary key (skill_name, version_number)
);

create table skill_runs (
    run_id text primary key,
    session_id text references sessions (session_id),
    project_id text references projects (project_id),
    skill_name text not null,
    run_status text not null check (run_status in ('running', 'ok', 'failed')),
    run_inputs text not null check (json_valid(run_inputs)),
    report_text text,
    version_number integer not null,
    started_at text not null,
    finished_at text,
    foreign key (skill_name, version_number)
    references skills (skill_name, version_number)
);

-- Own XBRL concepts; a formula is weighted reported concepts, as JSON.
create table concepts (
    concept_name text not null,
    definition_text text not null,
    concept_formula text not null check (json_valid(concept_formula)),
    version_number integer not null,
    created_at text not null,
    primary key (concept_name, version_number)
);

create table concept_values (
    concept_name text not null,
    cik text not null,
    unit_name text not null,
    value_basis text not null check (json_valid(value_basis)),
    version_number integer not null,
    concept_value real not null,
    period_end_date text not null,
    computed_at text not null,
    primary key (concept_name, version_number, cik, period_end_date),
    foreign key (concept_name, version_number)
    references concepts (concept_name, version_number)
);
