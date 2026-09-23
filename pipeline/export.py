"""Orchestrates the dashboard_* export: pull source tables from Synapse,
build the four tidy tables, apply suppression, validate, write JSON.

Run locally (after `az login`):
    python -m pipeline.export

In CI, AZURE_CLIENT_ID/SECRET/TENANT_ID env vars stand in for `az login`
(see connection.py and .github/workflows/sync-dashboard-data.yml).
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from . import connection
from .build_capacity import build_capacity_quarterly_rows, build_capacity_rows, build_capacity_yearly_rows
from .build_flow import build_flow_quarterly_rows, build_flow_rows, build_flow_yearly_rows, build_resource_access_rows
from .build_length import build_length_rows
from .build_return_cohorts import build_return_cohort_rows
from .config import DIMENSION_COLUMNS, PROJECT_TYPE_CODE_TEXT_TO_HUD, RACE_DIMENSIONS, RETURN_WINDOW_DAYS, get_export_window, month_before

# The 8 derived race_* columns (see demographics.py's compute_race_rollups),
# reused at both client_demographics merge sites below — sourced from
# DIMENSION_COLUMNS so this can't silently drift out of sync with config.py's
# own RACE_DIMENSIONS -> column-name mapping.
RACE_ROLLUP_COLUMNS = [DIMENSION_COLUMNS[d] for d in RACE_DIMENSIONS]
from .demographics import compute_gender_rollups, compute_race_rollups
from .suppression import (
    TRUE_COUNT_COL,
    apply_crosstab_secondary_suppression,
    apply_full_suppression_pipeline,
    apply_insufficient_population_fallback,
    apply_race_crossdim_suppression,
    suppress_small_secondary_count,
    validate,
    validate_crosstab,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def _scope_to_window(df: pd.DataFrame, date_col: str, start: date, end: date) -> pd.DataFrame:
    return df[(df[date_col] >= pd.Timestamp(start)) & (df[date_col] <= pd.Timestamp(end))]


def _to_json_records(df: pd.DataFrame, date_cols: list[str]) -> list[dict]:
    df = df.drop(columns=[TRUE_COUNT_COL], errors="ignore").copy()
    for col in date_cols:
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    # NaN/NaT -> null in the JSON output, not the string "NaN"
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _write(name: str, records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(records, indent=2))
    print(f"wrote {len(records)} rows -> {path}")


def main():
    start, end = get_export_window()
    print(f"export window: {start} .. {end}")
    as_of = pd.Timestamp(date.today())

    conn = connection.get_connection()

    # Client_Demographics: per-person (PersonalID) demographic rollups (the
    # 8 race_* columns, GenderIdentity/GenderAlignment) plus VeteranStatus —
    # joined into both episode_systemwide and All_Program_Enrollments below,
    # neither of which carries these natively. Synapse table is singular ("client_demographic"),
    # unlike its Looker view name / the notebook it was ported from —
    # confirmed against INFORMATION_SCHEMA.TABLES directly, not assumed.
    client_demographics = connection.query(conn, "client_demographic")
    # GenderIdentity/GenderAlignment and the 8 race_* rollup columns are all
    # computed here (once, person-level), not native Synapse columns — see
    # demographics.py for why they're derived from GenderExpanded/the raw
    # RaceAndEthnicity_* flags rather than the plain Gender/RaceAndEthnicity
    # summary columns.
    client_demographics = compute_gender_rollups(client_demographics)
    client_demographics = compute_race_rollups(client_demographics)

    # Pull with no date trim for episode_systemwide: return-cohort detection
    # needs to see up to RETURN_WINDOW_DAYS past the window's end, and the
    # length/flow builders trim to the window themselves below.
    all_episodes = connection.query(conn, "episode_systemwide")
    all_episodes["TimePeriodStartDate"] = pd.to_datetime(all_episodes["TimePeriodStartDate"])
    all_episodes["EpisodeStartDate"] = pd.to_datetime(all_episodes["EpisodeStartDate"])
    all_episodes["EpisodeEndDate"] = pd.to_datetime(all_episodes["EpisodeEndDate"])
    # episode_systemwide fans out one row per (PersonalID, ClientUniqueIdentifier)
    # pair for anyone with multiple CUIs on file (see Episode_Systemwide notebook's
    # final CUI-merge step) — every column but ClientUniqueIdentifier, which we
    # never use, is identical across the fan-out, so this collapses it safely
    # without risking merging two genuinely different episode-months.
    all_episodes = all_episodes.drop_duplicates(subset=["PersonalID", "EpisodeID", "TimePeriodStartDate"])
    all_episodes = all_episodes.merge(
        client_demographics[["PersonalID", *RACE_ROLLUP_COLUMNS, "GenderIdentity", "GenderAlignment", "VeteranStatus"]],
        on="PersonalID",
        how="left",
    )

    episodes_in_window = _scope_to_window(all_episodes, "TimePeriodStartDate", start, end)
    # One extra month before the window, so build_flow_rows/
    # build_flow_yearly_rows can resolve a true prior_month for the
    # window's own first published month/year — without it, anyone whose
    # episode started before the window (but is still open) reads as
    # brand-new inflow instead of already active. Never published itself
    # (window_start still gates what actually gets emitted below); every
    # other builder (length, return cohorts, resource access) doesn't need
    # this lookback and keeps using episodes_in_window.
    episodes_with_lookback = _scope_to_window(all_episodes, "TimePeriodStartDate", month_before(start), end)

    episode_ce = connection.query(conn, "episode_ce")
    episode_ce["CEEntryDate"] = pd.to_datetime(episode_ce["CEEntryDate"])
    episode_ce["CEExitDate"] = pd.to_datetime(episode_ce["CEExitDate"])

    performance_metrics = connection.query(conn, "program_performance_metrics")
    performance_metrics["TimePeriodStartDate"] = pd.to_datetime(performance_metrics["TimePeriodStartDate"])
    performance_metrics["TimePeriodEndDate"] = pd.to_datetime(performance_metrics["TimePeriodEndDate"])
    performance_metrics = _scope_to_window(performance_metrics, "TimePeriodStartDate", start, end)

    program_attributes = connection.query(conn, "program_attributes")
    # Synapse stores the human-readable HUD label here, not the numeric code
    # CAPACITY_PROJECT_TYPE_GROUPS is keyed by — see config.py.
    program_attributes["ProjectTypeCode"] = program_attributes["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)

    # --- dashboard_flow_monthly ---
    flow_df = build_flow_rows(episodes_with_lookback, episode_ce, window_start=pd.Timestamp(start))

    enrollments = connection.query(conn, "all_program_enrollments")
    enrollments["ProjectStartDate"] = pd.to_datetime(enrollments["ProjectStartDate"])
    enrollments["ProjectExitDate"] = pd.to_datetime(enrollments["ProjectExitDate"])
    # Same text-label-vs-numeric-code mismatch as program_attributes above.
    enrollments["ProjectTypeCode"] = enrollments["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)
    # All_Program_Enrollments has no monthly grain of its own (each row spans
    # ProjectStartDate..ProjectExitDate) — build_resource_access_rows expands
    # it against the same month list every other table uses.
    months_in_window = sorted(episodes_in_window["TimePeriodStartDate"].unique())
    resource_df = build_resource_access_rows(enrollments, client_demographics, months_in_window)
    flow_df = pd.concat([flow_df, resource_df], ignore_index=True)

    flow_df = apply_full_suppression_pipeline(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])
    # Extra pass, on top of the above: protects the indiv_flow_* cross-tab
    # cells' row/column totals, which the primary pass's grouping (keyed
    # by flow_type, and these each have their own distinct flow_type) never
    # treats as siblings of each other — see apply_crosstab_secondary_suppression.
    # group_cols includes dimension/category (not just month/population_segment):
    # indiv_flow_* rows now exist once per demographic category too (see
    # build_flow_rows), so without this a "row"/"column" group would pool
    # cells from unrelated demographic slices as if they were the same
    # cross-tab.
    flow_df = apply_crosstab_secondary_suppression(flow_df, group_cols=["month", "population_segment", "dimension", "category"])
    # The 8 race_* dimensions overlap (a person can be "Included" in more
    # than one) — see apply_race_crossdim_suppression's own docstring for
    # the cross-dimension inclusion-exclusion leak that opens up on its
    # own, independent of the within-dimension protection already applied
    # above.
    flow_df = apply_race_crossdim_suppression(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"], race_dimensions=RACE_DIMENSIONS)
    # A demographic category small enough (crossed with a small population
    # segment) can leave a group with literally nothing left to hide behind
    # — see apply_insufficient_population_fallback's own docstring. Rather
    # than let validate()/validate_crosstab() hard-fail the whole export
    # over one unresolvable slice, blank that exact (month, population
    # segment, dimension, category) scope entirely; the frontend shows a
    # "population too small to display" message for it instead of numbers.
    flow_df = apply_insufficient_population_fallback(
        flow_df,
        period_col="month",
        main_group_cols=["month", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["month", "population_segment", "dimension", "category"],
    )
    flow_violations = validate(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])
    flow_violations += validate_crosstab(flow_df, group_cols=["month", "population_segment", "dimension", "category"])

    # --- dashboard_flow_yearly (true distinct-person experienced_homelessness
    # and indiv_* partition per year — see build_flow_yearly_rows for why
    # these can't just be summed from dashboard_flow_monthly's per-month
    # figures) ---
    flow_yearly_df = build_flow_yearly_rows(episodes_with_lookback, window_start=pd.Timestamp(start))
    flow_yearly_df = apply_full_suppression_pipeline(
        flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"]
    )
    flow_yearly_df = apply_crosstab_secondary_suppression(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "category"])
    flow_yearly_df = apply_race_crossdim_suppression(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"], race_dimensions=RACE_DIMENSIONS)
    flow_yearly_df = apply_insufficient_population_fallback(
        flow_yearly_df,
        period_col="year",
        main_group_cols=["year", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["year", "population_segment", "dimension", "category"],
    )
    flow_yearly_violations = validate(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"])
    flow_yearly_violations += validate_crosstab(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "category"])

    # --- dashboard_flow_quarterly (drill-down granularity for OutflowSection's
    # pills — same "can't be summed from monthly cells" rationale as yearly,
    # see build_flow_quarterly_rows) ---
    flow_quarterly_df = build_flow_quarterly_rows(episodes_with_lookback, window_start=pd.Timestamp(start))
    flow_quarterly_df = apply_full_suppression_pipeline(
        flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"]
    )
    flow_quarterly_df = apply_crosstab_secondary_suppression(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])
    flow_quarterly_df = apply_race_crossdim_suppression(
        flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"], race_dimensions=RACE_DIMENSIONS
    )
    flow_quarterly_df = apply_insufficient_population_fallback(
        flow_quarterly_df,
        period_col="quarter",
        main_group_cols=["quarter", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["quarter", "population_segment", "dimension", "category"],
    )
    flow_quarterly_violations = validate(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"])
    flow_quarterly_violations += validate_crosstab(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])

    # --- dashboard_length_monthly ---
    length_df = build_length_rows(episodes_in_window)
    length_df = apply_full_suppression_pipeline(length_df, group_cols=["month", "population_segment", "dimension"], count_col="count")
    length_df = apply_race_crossdim_suppression(
        length_df, group_cols=["month", "population_segment", "dimension"], race_dimensions=RACE_DIMENSIONS, count_col="count"
    )
    # No indiv_flow_* cross-tab in this table (crosstab_group_cols is
    # unused — see apply_insufficient_population_fallback's own guard).
    length_df = apply_insufficient_population_fallback(
        length_df,
        period_col="month",
        main_group_cols=["month", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    length_violations = validate(length_df, group_cols=["month", "population_segment", "dimension"], count_col="count")
    # The suppression pipeline only nulls the count column itself — the
    # derived distribution stats are just as revealing for a small n, so they
    # must be nulled alongside it, not left populated next to a "*"/"**".
    length_df.loc[length_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]] = None
    length_df = length_df.rename(columns={"count": "n"})

    # --- dashboard_return_cohorts ---
    return_df = build_return_cohort_rows(episodes_in_window, all_episodes, as_of=as_of)
    return_df = return_df.rename(columns={"n_exited": "count"})
    return_df = apply_full_suppression_pipeline(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_df = apply_race_crossdim_suppression(
        return_df, group_cols=["exit_quarter", "population_segment", "dimension"], race_dimensions=RACE_DIMENSIONS, count_col="count"
    )
    return_df = apply_insufficient_population_fallback(
        return_df,
        period_col="exit_quarter",
        main_group_cols=["exit_quarter", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    return_violations = validate(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_df = return_df.rename(columns={"count": "n_exited"})
    return_df.loc[return_df["suppression_marker"].notna(), "n_returned"] = None
    return_df.loc[return_df["suppression_marker"].notna(), "pct_returned"] = None
    # n_exited being above threshold doesn't mean n_returned is — a cohort
    # can have plenty of exits but only a handful who returned. Suppressed
    # independently, row-local (see suppress_small_secondary_count) so a
    # well-populated row isn't hidden entirely just because this one
    # derived count is small; the frontend shows the exited total with the
    # return split marked as withheld instead.
    return_df = suppress_small_secondary_count(return_df, count_col="n_returned", marker_col="return_suppression_marker", extra_cols=["pct_returned"])

    # --- dashboard_capacity_monthly / _quarterly / _yearly (no
    # suppression: aggregate inventory data, not person-level) ---
    capacity_df = build_capacity_rows(performance_metrics, program_attributes, as_of=as_of)
    capacity_quarterly_df = build_capacity_quarterly_rows(performance_metrics, program_attributes, as_of=as_of)
    # Yearly deliberately doesn't get this treatment — the current
    # (incomplete) year is intentionally included there, labeled
    # "year to date" by the frontend's existing Year selector, unlike
    # the quarterly/monthly charts which should only ever show complete
    # periods.
    capacity_yearly_df = build_capacity_yearly_rows(performance_metrics, program_attributes)

    all_violations = flow_violations + flow_yearly_violations + flow_quarterly_violations + length_violations + return_violations
    if all_violations:
        print("SUPPRESSION VALIDATION FAILED:", file=sys.stderr)
        for v in all_violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    # inflow_bucket/outflow_bucket only exist to give
    # apply_crosstab_secondary_suppression a clean grouping key — internal,
    # like TRUE_COUNT_COL, never written to the exported JSON.
    flow_df = flow_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")
    flow_yearly_df = flow_yearly_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")
    flow_quarterly_df = flow_quarterly_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")

    _write("dashboard_flow_monthly.json", _to_json_records(flow_df, ["month"]))
    _write("dashboard_flow_yearly.json", _to_json_records(flow_yearly_df, []))
    _write("dashboard_flow_quarterly.json", _to_json_records(flow_quarterly_df, ["quarter"]))
    _write("dashboard_length_monthly.json", _to_json_records(length_df, ["month"]))
    _write("dashboard_return_cohorts.json", _to_json_records(return_df, ["exit_quarter"]))
    _write("dashboard_capacity_monthly.json", _to_json_records(capacity_df, ["month"]))
    _write("dashboard_capacity_quarterly.json", _to_json_records(capacity_quarterly_df, ["quarter"]))
    _write("dashboard_capacity_yearly.json", _to_json_records(capacity_yearly_df, []))


if __name__ == "__main__":
    main()
