# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
"""Tools for skills and their runs, and own XBRL concepts."""

from mcp.server import mcpserver

from userdata import account
from userdata import market
from userdata import sec
from userdata import stores


async def save_skill(
    context: mcpserver.Context,
    skill_name: str,
    skill_text: str,
    skill_settings: account.Row,
) -> account.Row:
    """Saves a new version of a skill; old versions are kept."""
    store = stores.from_context(context).account
    row = {
        "skill_name": skill_name,
        "skill_text": skill_text,
        "skill_settings": skill_settings,
        "version_number": account.next_version(store, "skills", skill_name),
        "created_at": account.now(),
    }
    return account.save(store, "skills", row, "skill_saved")


async def start_run(
    context: mcpserver.Context,
    skill_name: str,
    run_inputs: account.Row,
    session_id: str | None = None,
) -> account.Row:
    """Starts a run of the latest version of a skill."""
    store = stores.from_context(context).account
    latest = account.next_version(store, "skills", skill_name) - 1
    row = {
        "run_id": account.new_id(),
        "session_id": session_id,
        "skill_name": skill_name,
        "run_status": "running",
        "run_inputs": run_inputs,
        "version_number": latest,
        "started_at": account.now(),
    }
    return account.save(store, "skill_runs", row, "run_started")


async def finish_run(
    context: mcpserver.Context, run_id: str, run_status: str, report: str
) -> account.Row:
    """Ends a run as "ok" or "failed" and keeps its report."""
    store = stores.from_context(context).account
    store.execute(
        "update skill_runs set run_status = ?, report_text = ?,"
        " finished_at = ? where run_id = ?",
        (run_status, report, account.now(), run_id),
    )
    details = {"run_id": run_id, "run_status": run_status}
    return account.record(store, "run_finished", details)


async def define_concept(
    context: mcpserver.Context,
    concept_name: str,
    definition_text: str,
    concept_formula: list[account.Row],
) -> account.Row:
    """Defines an own XBRL concept as a weighted sum of reported ones."""
    store = stores.from_context(context).account
    row = {
        "concept_name": concept_name,
        "definition_text": definition_text,
        "concept_formula": concept_formula,
        "version_number": account.next_version(store, "concepts", concept_name),
        "created_at": account.now(),
    }
    return account.save(store, "concepts", row, "concept_defined", "michael")


async def compute_concept(
    context: mcpserver.Context, concept_name: str, ticker: str
) -> list[account.Row]:
    """Computes an own concept from a company's facts and stores it."""
    opened = stores.from_context(context)
    concept = account.latest_concept(opened.account, concept_name)
    cik = sec.pull_company(opened.market, ticker)["cik"]
    formula = concept["concept_formula"]
    values = market.concept_values(opened.market, formula, cik)
    for value in values:
        row = value | {
            "concept_name": concept_name,
            "cik": cik,
            "version_number": concept["version_number"],
            "computed_at": account.now(),
        }
        account.save(
            opened.account,
            "concept_values",
            row,
            "concept_computed",
            replace=True,
        )
    return values


TOOLS = (
    save_skill,
    start_run,
    finish_run,
    define_concept,
    compute_concept,
)
