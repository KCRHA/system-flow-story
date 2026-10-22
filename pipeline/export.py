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
from .build_flow import (
    INFLOW_BUCKET_KEYS,
    OUTFLOW_BUCKET_KEYS,
    build_flow_quarterly_rows,
    build_flow_rows,
    build_flow_yearly_rows,
    build_resource_access_rows,
)
from .build_length import build_length_rows
from .build_length_by_exit import (
    build_length_by_exit_rows,
    build_length_headline_monthly_rows,
    build_length_headline_quarterly_rows,
    build_length_headline_rows,
)
from .build_return_cohorts import build_return_cohort_rows
from .config import (
    DIMENSION_COLUMNS,
    PROJECT_ENGAGEMENT_DIMENSIONS,
    PROJECT_TYPE_CODE_TEXT_TO_HUD,
    RACE_DIMENSIONS,
    RETURN_WINDOW_DAYS,
    # TOP_10_KING_COUNTY_CITIES,  # last_known_city filter temporarily disabled
    get_export_window,
    month_before,
)

# The 8 derived race_* columns (see demographics.py's compute_race_rollups),
# reused at both client_demographics merge sites below — sourced from
# DIMENSION_COLUMNS so this can't silently drift out of sync with config.py's
# own RACE_DIMENSIONS -> column-name mapping.
RACE_ROLLUP_COLUMNS = [DIMENSION_COLUMNS[d] for d in RACE_DIMENSIONS]

# Both groups of dimensions overlap internally (a person can be "Included"
# in more than one race_* dimension, or more than one project_engaged_*
# dimension) — see apply_race_crossdim_suppression's own docstring for the
# cross-dimension inclusion-exclusion leak this opens up. Passed to that
# function as ONE combined list, not two separate RACE_DIMENSIONS/
# PROJECT_ENGAGEMENT_DIMENSIONS calls: the function only compares pairs
# within whatever list it's given, so two separate calls would check
# race-vs-race and project-vs-project overlaps but silently miss a
# race_* dimension paired with a project_engaged_* one — a real,
# verified disclosure gap (e.g. race_black + project_engaged_ce - overall
# landing under SUPPRESSION_THRESHOLD) caught by auditing the actual
# exported JSON.
CROSSDIM_OVERLAP_DIMENSIONS = [*RACE_DIMENSIONS, *PROJECT_ENGAGEMENT_DIMENSIONS]
from .demographics import compute_gender_rollups, compute_race_rollups
from .suppression import (
    TRUE_COUNT_COL,
    apply_crosstab_secondary_suppression,
    apply_full_suppression_pipeline,
    apply_insufficient_population_fallback,
    apply_race_crossdim_suppression,
    apply_sankey_marginal_suppression,
    suppress_small_secondary_count,
    validate,
    validate_crosstab,
    validate_sankey_marginal,
)

# The sankey's inflow buckets (already_active/newly_homeless/
# return_from_housed/return_from_inactive) are a true partition of
# experienced_homelessness, and so are its outflow buckets (still_active/
# aged_out/permanently_housed/inactive/deceased) — see build_flow.py's
# _partition_by_individual docstring. Sourced from build_flow.py's own
# INFLOW_BUCKET_KEYS/OUTFLOW_BUCKET_KEYS (with the "indiv_" prefix those
# flow_types are actually published under — see build_flow_rows) so this
# can't silently drift out of sync with the sankey's real bucket set.
SANKEY_BUCKET_FLOW_TYPE_GROUPS = [
    [f"indiv_{key}" for key in INFLOW_BUCKET_KEYS],
    [f"indiv_{key}" for key in OUTFLOW_BUCKET_KEYS],
]

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


# dashboard_flow_monthly split one file per calendar year (~35-45MB each)
# instead of one ~250MB blob — a single file exceeds GitHub's 100MB push
# limit once the full export window is included, and the frontend only
# ever needs one year's worth of monthly rows loaded at a time (see
# loadData.js's loadMonthlyFlowForYear). Old per-year files from a since-
# shrunk export window are removed so a stale year never lingers.
def _write_monthly_flow_split(records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("dashboard_flow_monthly_*.json"):
        stale.unlink()
    by_year: dict[str, list[dict]] = {}
    for record in records:
        by_year.setdefault(record["month"][:4], []).append(record)
    for year, year_records in sorted(by_year.items()):
        _write(f"dashboard_flow_monthly_{year}.json", year_records)


def main():
    start, end = get_export_window()
    print(f"export window: {start} .. {end}")
    as_of = pd.Timestamp(date.today())

    conn = connection.get_connection()

    # Client_Demographics: per-person (PersonalID) demographic rollups (the
    # 8 race_* columns, GenderIdentity/GenderAlignment) plus VeteranStatus and
    # LastKnownSubregion — joined into both episode_systemwide and
    # All_Program_Enrollments below, neither of which carries these natively.
    # (LastKnownCity/last_known_city filter temporarily disabled.)
    # Synapse table is singular ("client_demographic"), unlike its Looker
    # view name / the notebook it was ported from — confirmed against
    # INFORMATION_SCHEMA.TABLES directly, not assumed.
    client_demographics = connection.query(conn, "client_demographic")
    # GenderIdentity/GenderAlignment and the 8 race_* rollup columns are all
    # computed here (once, person-level), not native Synapse columns — see
    # demographics.py for why they're derived from GenderExpanded/the raw
    # RaceAndEthnicity_* flags rather than the plain Gender/RaceAndEthnicity
    # summary columns.
    client_demographics = compute_gender_rollups(client_demographics)
    client_demographics = compute_race_rollups(client_demographics)
    # LastKnownSubregion (native column, Client_Demographics.ipynb's own
    # city -> King County subregion mapping) is NaN for anyone whose last
    # known address didn't map to a subregion (outside King County, an
    # unincorporated area, or never collected) — filled to "Unknown" so the
    # dimension partitions cleanly for suppression, same as GenderIdentity's
    # own "Unknown" bucket. Hidden from the frontend filter by App.jsx's
    # HIDDEN_CATEGORIES set, same as that bucket too.
    client_demographics["LastKnownSubregion"] = client_demographics["LastKnownSubregion"].fillna("Unknown")
    # last_known_city filter temporarily disabled.
    # LastKnownCity (native column, the free-text city value Client_Demographics
    # .ipynb's subregion mapping is itself derived from) has one distinct value
    # per city ever recorded, which is too many to offer as a filter —
    # collapsed here to just TOP_10_KING_COUNTY_CITIES, with everyone else
    # (a smaller KC city, somewhere outside King County, or NaN/never
    # collected) folded into a single "Other" category so the dimension
    # still partitions cleanly for suppression. See config.py's
    # TOP_10_KING_COUNTY_CITIES/last_known_city comments.
    # client_demographics["LastKnownCity"] = client_demographics["LastKnownCity"].where(
    #     client_demographics["LastKnownCity"].isin(TOP_10_KING_COUNTY_CITIES), "Other"
    # )

    # BirthDate: neither client_demographic nor episode_systemwide carries
    # it — both source notebooks drop it before publishing to Synapse (see
    # age.py's module docstring) — so it's pulled straight from Looker's
    # client_model view instead, the same view/fields Episode_Systemwide's
    # own notebook uses for its own (frozen, episode-start-only) age tier
    # computation. Merged onto client_demographics here (not queried
    # separately per-caller) so it rides along with VeteranStatus/
    # LastKnownSubregion through both of this file's existing
    # client_demographics merge sites below, and build_flow.py's
    # build_resource_access_rows's own client_demographics merge, with no
    # further plumbing.
    birth_dates = connection.query_looker(
        conn,
        "client_model",
        fields=["client_model.personal_id", "client_model.birth_date"],
        filters={"client_model.deleted": "No"},
    )
    # Looker's inline-query CSV returns columns by field LABEL, not field id
    # (e.g. "Client Model Personal Id"), so positional assignment — same as
    # Episode_Systemwide's own identical birth_dates pull — rather than a
    # rename() keyed to an exact label string this pipeline can't confirm
    # without a live Looker credential.
    birth_dates.columns = ["PersonalID", "BirthDate"]
    # Parsed once, here, same as every other date column this file loads
    # (EpisodeStartDate/TimePeriodStartDate/EpisodeEndDate below) — age.py's
    # age_in_years() is called from inside filter_population, often once per
    # month per population segment, so leaving BirthDate as raw strings
    # would re-parse it from scratch (and re-warn pandas's "could not infer
    # format" fallback) on every single one of those calls instead of once.
    birth_dates["BirthDate"] = pd.to_datetime(birth_dates["BirthDate"], errors="coerce")
    client_demographics = client_demographics.merge(birth_dates, on="PersonalID", how="left")

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
        client_demographics[
            [
                "PersonalID",
                *RACE_ROLLUP_COLUMNS,
                "GenderIdentity",
                "GenderAlignment",
                "VeteranStatus",
                "LastKnownSubregion",
                "BirthDate",
                # "LastKnownCity",  # last_known_city filter temporarily disabled
            ]
        ],
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

    # All_Program_Enrollments — loaded ahead of build_flow_rows below, not
    # just build_resource_access_rows, since build_flow_rows/yearly/
    # quarterly now also need it to resolve the project_engaged_*
    # dimensions (see build_flow.py's _project_engagement_category). Not
    # date-scoped to the window: a long-open enrollment that started years
    # earlier must still count as overlapping this window's periods.
    enrollments = connection.query(conn, "all_program_enrollments")
    enrollments["ProjectStartDate"] = pd.to_datetime(enrollments["ProjectStartDate"])
    enrollments["ProjectExitDate"] = pd.to_datetime(enrollments["ProjectExitDate"])
    # Same text-label-vs-numeric-code mismatch as program_attributes above.
    enrollments["ProjectTypeCode"] = enrollments["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)

    # --- dashboard_flow_monthly ---
    flow_df = build_flow_rows(episodes_with_lookback, episode_ce, enrollments, window_start=pd.Timestamp(start))

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
    # Separate from the crosstab pass above: protects the sankey's own
    # inflow-buckets-sum-to-total and outflow-buckets-sum-to-total
    # relationships (indiv_already_active + indiv_newly_homeless + ... ==
    # experienced_homelessness), which neither the main pass (flow_type is
    # part of its own group_cols, so these never appear as siblings of
    # each other) nor the crosstab pass (that's a different relationship —
    # pair cells summing to one bucket's own marginal) ever checks — see
    # apply_sankey_marginal_suppression.
    flow_df = apply_sankey_marginal_suppression(flow_df, group_cols=["month", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)
    # See CROSSDIM_OVERLAP_DIMENSIONS' own comment — one combined pass, not
    # separate race_*/project_engaged_* ones, so a race-vs-project_engaged
    # overlap pair is checked too, not just same-group pairs.
    flow_df = apply_race_crossdim_suppression(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS)
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
        sankey_bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS,
    )
    flow_violations = validate(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])
    flow_violations += validate_crosstab(flow_df, group_cols=["month", "population_segment", "dimension", "category"])
    flow_violations += validate_sankey_marginal(flow_df, group_cols=["month", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)

    # --- dashboard_flow_yearly (true distinct-person experienced_homelessness
    # and indiv_* partition per year — see build_flow_yearly_rows for why
    # these can't just be summed from dashboard_flow_monthly's per-month
    # figures) ---
    flow_yearly_df = build_flow_yearly_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    flow_yearly_df = apply_full_suppression_pipeline(
        flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"]
    )
    flow_yearly_df = apply_crosstab_secondary_suppression(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "category"])
    flow_yearly_df = apply_sankey_marginal_suppression(flow_yearly_df, group_cols=["year", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)
    flow_yearly_df = apply_race_crossdim_suppression(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS)
    flow_yearly_df = apply_insufficient_population_fallback(
        flow_yearly_df,
        period_col="year",
        main_group_cols=["year", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["year", "population_segment", "dimension", "category"],
        sankey_bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS,
    )
    flow_yearly_violations = validate(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "flow_type"])
    flow_yearly_violations += validate_crosstab(flow_yearly_df, group_cols=["year", "population_segment", "dimension", "category"])
    flow_yearly_violations += validate_sankey_marginal(flow_yearly_df, group_cols=["year", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)

    # --- dashboard_flow_quarterly (drill-down granularity for OutflowSection's
    # pills — same "can't be summed from monthly cells" rationale as yearly,
    # see build_flow_quarterly_rows) ---
    flow_quarterly_df = build_flow_quarterly_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    flow_quarterly_df = apply_full_suppression_pipeline(
        flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"]
    )
    flow_quarterly_df = apply_crosstab_secondary_suppression(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])
    flow_quarterly_df = apply_sankey_marginal_suppression(
        flow_quarterly_df, group_cols=["quarter", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS
    )
    flow_quarterly_df = apply_race_crossdim_suppression(
        flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS
    )
    flow_quarterly_df = apply_insufficient_population_fallback(
        flow_quarterly_df,
        period_col="quarter",
        main_group_cols=["quarter", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["quarter", "population_segment", "dimension", "category"],
        sankey_bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS,
    )
    flow_quarterly_violations = validate(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"])
    flow_quarterly_violations += validate_crosstab(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])
    flow_quarterly_violations += validate_sankey_marginal(
        flow_quarterly_df, group_cols=["quarter", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS
    )

    # --- dashboard_length_monthly ---
    length_df = build_length_rows(episodes_in_window, enrollments)
    length_df = apply_full_suppression_pipeline(length_df, group_cols=["month", "population_segment", "dimension"], count_col="count")
    length_df = apply_race_crossdim_suppression(
        length_df, group_cols=["month", "population_segment", "dimension"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS, count_col="count"
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

    # --- dashboard_length_by_exit_monthly (split by permanently_housed/
    # inactive/aged_out — see build_length_by_exit.py's module docstring for
    # why the plain dashboard_length_monthly above pools everyone together
    # in a way that was causing confusion about what it actually measured).
    # episodes_with_lookback + window_start, not episodes_in_window: aged-out
    # detection needs a true prior_month for the window's own first
    # published month, same reason build_flow_rows needs it.
    length_by_exit_df = build_length_by_exit_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    length_by_exit_df = apply_full_suppression_pipeline(
        length_by_exit_df, group_cols=["month", "population_segment", "dimension", "exit_type"], count_col="count"
    )
    length_by_exit_df = apply_race_crossdim_suppression(
        length_by_exit_df,
        group_cols=["month", "population_segment", "dimension", "exit_type"],
        race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS,
        count_col="count",
    )
    # apply_insufficient_population_fallback's blanking key only recognizes
    # a column literally named "flow_type" (see its own _key/has_flow_type —
    # every dashboard_flow_* table already uses that name) — alias exit_type
    # to it for this one call so blanking stays scoped to the specific
    # exit_type that triggered it, instead of collapsing to (month,
    # population_segment, dimension, category) alone and blanking every
    # exit_type in that slice together.
    length_by_exit_df = length_by_exit_df.rename(columns={"exit_type": "flow_type"})
    length_by_exit_df = apply_insufficient_population_fallback(
        length_by_exit_df,
        period_col="month",
        main_group_cols=["month", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=[],
        count_col="count",
    )
    length_by_exit_df = length_by_exit_df.rename(columns={"flow_type": "exit_type"})
    length_by_exit_violations = validate(
        length_by_exit_df, group_cols=["month", "population_segment", "dimension", "exit_type"], count_col="count"
    )
    length_by_exit_df.loc[length_by_exit_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]] = None
    length_by_exit_df = length_by_exit_df.rename(columns={"count": "n"})

    # --- dashboard_length_headline_yearly (single pooled median — see
    # build_length_by_exit.py's own docstring for exactly what this pools) ---
    length_headline_df = build_length_headline_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    length_headline_df = apply_full_suppression_pipeline(
        length_headline_df, group_cols=["year", "population_segment", "dimension"], count_col="count"
    )
    length_headline_df = apply_race_crossdim_suppression(
        length_headline_df, group_cols=["year", "population_segment", "dimension"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS, count_col="count"
    )
    length_headline_df = apply_insufficient_population_fallback(
        length_headline_df,
        period_col="year",
        main_group_cols=["year", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    length_headline_violations = validate(length_headline_df, group_cols=["year", "population_segment", "dimension"], count_col="count")
    length_headline_df.loc[length_headline_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]] = None
    length_headline_df = length_headline_df.rename(columns={"count": "n"})

    # --- dashboard_length_headline_monthly / _quarterly (same pooled
    # definition as the yearly table above, just at finer grain — powers
    # LengthSection's headline KPI card whenever a reader drills into a
    # specific month/quarter instead of browsing the full year) ---
    length_headline_monthly_df = build_length_headline_monthly_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    length_headline_monthly_df = apply_full_suppression_pipeline(
        length_headline_monthly_df, group_cols=["month", "population_segment", "dimension"], count_col="count"
    )
    length_headline_monthly_df = apply_race_crossdim_suppression(
        length_headline_monthly_df, group_cols=["month", "population_segment", "dimension"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS, count_col="count"
    )
    length_headline_monthly_df = apply_insufficient_population_fallback(
        length_headline_monthly_df,
        period_col="month",
        main_group_cols=["month", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    length_headline_monthly_violations = validate(
        length_headline_monthly_df, group_cols=["month", "population_segment", "dimension"], count_col="count"
    )
    length_headline_monthly_df.loc[
        length_headline_monthly_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]
    ] = None
    length_headline_monthly_df = length_headline_monthly_df.rename(columns={"count": "n"})

    length_headline_quarterly_df = build_length_headline_quarterly_rows(episodes_with_lookback, enrollments, window_start=pd.Timestamp(start))
    length_headline_quarterly_df = apply_full_suppression_pipeline(
        length_headline_quarterly_df, group_cols=["quarter", "population_segment", "dimension"], count_col="count"
    )
    length_headline_quarterly_df = apply_race_crossdim_suppression(
        length_headline_quarterly_df, group_cols=["quarter", "population_segment", "dimension"], race_dimensions=CROSSDIM_OVERLAP_DIMENSIONS, count_col="count"
    )
    length_headline_quarterly_df = apply_insufficient_population_fallback(
        length_headline_quarterly_df,
        period_col="quarter",
        main_group_cols=["quarter", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    length_headline_quarterly_violations = validate(
        length_headline_quarterly_df, group_cols=["quarter", "population_segment", "dimension"], count_col="count"
    )
    length_headline_quarterly_df.loc[
        length_headline_quarterly_df["suppression_marker"].notna(), ["median_days", "p25_days", "p75_days", "mean_days"]
    ] = None
    length_headline_quarterly_df = length_headline_quarterly_df.rename(columns={"count": "n"})

    # --- dashboard_return_cohorts ---
    return_df = build_return_cohort_rows(episodes_in_window, all_episodes, enrollments, as_of=as_of)
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

    all_violations = (
        flow_violations
        + flow_yearly_violations
        + flow_quarterly_violations
        + length_violations
        + length_by_exit_violations
        + length_headline_violations
        + length_headline_monthly_violations
        + length_headline_quarterly_violations
        + return_violations
    )
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

    _write_monthly_flow_split(_to_json_records(flow_df, ["month"]))
    _write("dashboard_flow_yearly.json", _to_json_records(flow_yearly_df, []))
    _write("dashboard_flow_quarterly.json", _to_json_records(flow_quarterly_df, ["quarter"]))
    _write("dashboard_length_monthly.json", _to_json_records(length_df, ["month"]))
    _write("dashboard_length_by_exit_monthly.json", _to_json_records(length_by_exit_df, ["month"]))
    _write("dashboard_length_headline_yearly.json", _to_json_records(length_headline_df, []))
    _write("dashboard_length_headline_monthly.json", _to_json_records(length_headline_monthly_df, ["month"]))
    _write("dashboard_length_headline_quarterly.json", _to_json_records(length_headline_quarterly_df, ["quarter"]))
    _write("dashboard_return_cohorts.json", _to_json_records(return_df, ["exit_quarter"]))
    _write("dashboard_capacity_monthly.json", _to_json_records(capacity_df, ["month"]))
    _write("dashboard_capacity_quarterly.json", _to_json_records(capacity_quarterly_df, ["quarter"]))
    _write("dashboard_capacity_yearly.json", _to_json_records(capacity_yearly_df, []))


if __name__ == "__main__":
    main()
