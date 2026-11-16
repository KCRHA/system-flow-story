"""Orchestrates the dashboard_* export: pull source tables from Synapse,
build the four tidy tables, apply suppression, validate, write JSON.

Run locally (after `az login`):
    python -m pipeline.export

In CI, AZURE_CLIENT_ID/SECRET/TENANT_ID env vars stand in for `az login`
(see connection.py and .github/workflows/sync-dashboard-data.yml).
"""
import json
import sys
import time
from datetime import date, datetime
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
    build_month_population_cache,
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
    DECEASED_IN_INACTIVE_FLOW_TYPE,
    DIMENSION_COLUMNS,
    HOUSEHOLD_TYPE_DIMENSIONS,
    LENGTH_FULL_STATS_MIN_N,
    PROJECT_ENGAGEMENT_DIMENSIONS,
    PROJECT_TYPE_CODE_TEXT_TO_HUD,
    RACE_DIMENSIONS,
    RETURN_WINDOW_DAYS,
    SUBREGION_ENGAGEMENT_DIMENSIONS,
    # TOP_10_KING_COUNTY_CITIES,  # last_known_city filter temporarily disabled
    get_export_window,
    month_before,
)

# The 8 derived race_* columns (see demographics.py's compute_race_rollups),
# reused at the client_demographics merge below — sourced from
# DIMENSION_COLUMNS so this can't silently drift out of sync with config.py's
# own RACE_DIMENSIONS -> column-name mapping.
RACE_ROLLUP_COLUMNS = [DIMENSION_COLUMNS[d] for d in RACE_DIMENSIONS]

# Overlapping binary dimensions: a person can be "Included" in more than
# one race_* (or project_engaged_*, engaged_in_subregion_*, or
# household_type_*) dimension at once. The frontend only ever shows each
# one's "Included" row (as one category of the virtual Race/Ethnicity,
# Project Type Engagement, Subregion Engagement or Household Type selection), and those Included rows can't be
# calculated from each other. Their "Not Included" rows are dropped before
# suppression (see _drop_overlap_not_included): published, they'd let anyone
# get Included as overall minus Not Included, and nothing on the dashboard
# uses them.
OVERLAPPING_BINARY_DIMENSIONS = [*RACE_DIMENSIONS, *PROJECT_ENGAGEMENT_DIMENSIONS, *SUBREGION_ENGAGEMENT_DIMENSIONS, *HOUSEHOLD_TYPE_DIMENSIONS]


def _drop_overlap_not_included(df: pd.DataFrame) -> pd.DataFrame:
    """Drops OVERLAPPING_BINARY_DIMENSIONS' "Not Included" rows. Run right
    after each build, before suppression, so each of those dimensions is a
    single-category group that never needs secondary suppression (there's
    no other category in the selection to calculate it from)."""
    drop = df["dimension"].isin(OVERLAPPING_BINARY_DIMENSIONS) & (df["category"] == "Not Included")
    return df[~drop].reset_index(drop=True)
from .demographics import compute_gender_rollups, compute_race_rollups
from .suppression import (
    DECEASED_COMBINED_HIGH_COL,
    DECEASED_HIGH_COL,
    DECEASED_LOW_COL,
    INSUFFICIENT_POPULATION_MARKER,
    apply_deceased_bands,
    unpublished_rows,
    validate_deceased_bands,
    TRUE_COUNT_COL,
    _group_keys,
    _violating_groups,
    apply_return_count_suppression,
    apply_crosstab_secondary_suppression,
    apply_full_suppression_pipeline,
    apply_insufficient_population_fallback,
    apply_sankey_marginal_suppression,
    validate,
    validate_crosstab,
    validate_sankey_marginal,
)

# The sankey's inflow buckets (already_active/newly_homeless/
# return_from_housed/return_from_inactive) are a true partition of
# experienced_homelessness, and so are its outflow buckets (still_active/
# aged_out/permanently_housed/inactive, deceased included) — see build_flow.py's
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
    # "Unknown" categories took part in suppression as hidden cells but are
    # never shown, so they're never published (see config.UNPUBLISHED_CATEGORIES).
    df = df[~unpublished_rows(df)]
    df = df.drop(columns=[TRUE_COUNT_COL, DECEASED_COMBINED_HIGH_COL], errors="ignore").copy()
    for col in date_cols:
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    # NaN/NaT -> null in the JSON output, not the string "NaN"
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    # count_low/count_high only exist on deceased_in_inactive rows published
    # as a band (see suppression.apply_deceased_bands); leaving them null on
    # every other row would just bloat the flow files.
    if DECEASED_LOW_COL in df.columns:
        for record in records:
            if record.get(DECEASED_LOW_COL) is None:
                record.pop(DECEASED_LOW_COL, None)
                record.pop(DECEASED_HIGH_COL, None)
    return records


def _split_deceased(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(flow rows, DECEASED_IN_INACTIVE_FLOW_TYPE rows). The deceased rows
    skip every count-suppression pass: they're published only as bands
    (see suppression.apply_deceased_bands), never as counts."""
    is_deceased = df["flow_type"] == DECEASED_IN_INACTIVE_FLOW_TYPE
    return df[~is_deceased].reset_index(drop=True), df[is_deceased].reset_index(drop=True)


# Timing instrumentation for the silent stretch between the event_systemwide
# Synapse fetch and the first _write() print — every build_*_rows call in
# between consumes `events`/`enrollments` via period_dimensions.py's
# per-period dimension resolution, so printing after each one (rather than
# just at the start/end of the whole stretch) pinpoints which specific
# table's builder is actually slow on a given run, instead of just
# confirming the whole block is slow. Returns the new checkpoint time so
# callers chain `t = _checkpoint(..., t)` and each printed duration is just
# that one step's own elapsed time, not a running cumulative total.
def _checkpoint(label: str, since: float) -> float:
    now = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}: {now - since:.1f}s")
    return now


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


# dashboard_flow_quarterly split one file per dimension (race_aian,
# gender_identity, engaged_in_subregion_east, etc. — a few hundred KB to a
# few MB each) instead of one ~110MB blob covering every dimension's full
# multi-year history at once. Unlike dashboard_flow_monthly (split by year,
# because OutflowSection only ever needs ONE year of monthly rows at a
# time — see loadMonthlyFlowForYear), the quarterly export's whole point is
# a full-history trend per dimension, so splitting by year wouldn't let the
# frontend load less; OutflowSection always filters quarterly rows down to
# exactly one (dimension, category) pair before using them (see its own
# scopedQuarterly), so the dimension is the axis that actually varies with
# what's needed on screen. "overall" is every reader's default demographic
# selection (see App.jsx's selectedDemographicType), so it's fetched
# eagerly same as every other small file; every other dimension is fetched
# only once a reader actually picks it — see loadData.js's
# loadQuarterlyFlowForDimension. Old per-dimension files from a dimension
# since removed are cleaned up the same way _write_monthly_flow_split does.
def _write_quarterly_flow_split(records: list[dict]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("dashboard_flow_quarterly_*.json"):
        stale.unlink()
    by_dimension: dict[str, list[dict]] = {}
    for record in records:
        by_dimension.setdefault(record["dimension"], []).append(record)
    for dimension, dimension_records in sorted(by_dimension.items()):
        _write(f"dashboard_flow_quarterly_{dimension}.json", dimension_records)


def _suppress_flow_yearly(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Full suppression + validation chain for a year-keyed flow table —
    shared by dashboard_flow_yearly and dashboard_flow_ytd_prior so the two
    can never drift apart. Returns (flow rows, deceased band rows, violations)."""
    df = _drop_overlap_not_included(df)
    df, deceased_df = _split_deceased(df)
    df = apply_full_suppression_pipeline(df, group_cols=["year", "population_segment", "dimension", "flow_type"])
    df = apply_crosstab_secondary_suppression(df, group_cols=["year", "population_segment", "dimension", "category"])
    df = apply_sankey_marginal_suppression(df, group_cols=["year", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)
    df = apply_insufficient_population_fallback(
        df,
        period_col="year",
        main_group_cols=["year", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["year", "population_segment", "dimension", "category"],
        sankey_bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS,
    )
    # How many of each inactive count are deceased, as a band (see
    # suppression.apply_deceased_bands). Needs the inactive cells' final markers.
    deceased_df = apply_deceased_bands(deceased_df, df, period_col="year")
    violations = validate(df, group_cols=["year", "population_segment", "dimension", "flow_type"])
    violations += validate_deceased_bands(deceased_df, df, period_col="year")
    violations += validate_crosstab(df, group_cols=["year", "population_segment", "dimension", "category"])
    violations += validate_sankey_marginal(df, group_cols=["year", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)
    return df, deceased_df, violations


def _suppress_capacity_household_count(df: pd.DataFrame, period_col: str, count_col: str) -> tuple[pd.DataFrame, list[str]]:
    """Applies suppression.py's existing primary/secondary logic, reused
    unmodified, to one of dashboard_capacity_*'s household-count columns
    (enrolled/exited/active — see build_capacity.py's own module docstring
    for why units_in_system/beds_in_system, pure bed/unit inventory, never
    go through this). Every row sharing (period_col, project_type) is one
    sibling group — the "Overall" scope plus its 6 named subregions (see
    build_capacity.py's _with_subregion_scopes) — the same "a visible total
    plus visible siblings can back-compute one hidden sibling" risk
    apply_sankey_marginal_suppression already guards against elsewhere,
    just keyed by subregion instead of flow_type bucket; no "dimension"
    column here for apply_full_suppression_pipeline to exclude an
    "overall" row from (unlike every other table's call), which is
    correct — the "Overall" subregion scope IS meant to be an eligible
    group member here, not a singleton excluded from its own group.

    Returns `count_col` nulled wherever suppressed, with its own dedicated
    f"{count_col}_suppression_marker" column rather than the shared
    "suppression_marker" name apply_full_suppression_pipeline writes —
    enrolled/exited/active each need independent suppression state on the
    same row, same reasoning as apply_return_count_suppression's own
    marker_col — plus this column's own validate() violations, for the
    caller to fold into the pipeline's usual hard gate."""
    group_cols = [period_col, "project_type"]
    df = apply_full_suppression_pipeline(df, group_cols=group_cols, count_col=count_col)
    # A group only fails validate() when none of its rows is left visible to
    # hide as a secondary — e.g. a quarter with one TH program, where
    # "Overall" and that program's subregion are the same small number.
    # Every count in it is already blank, so marking the group
    # insufficient_population (which validate() accepts as protection)
    # hides nothing new; it just stops that group failing the whole export.
    unresolved = _violating_groups(df, group_cols)
    if len(unresolved):
        in_unresolved = _group_keys(df, group_cols).isin(unresolved)
        df.loc[in_unresolved, "suppression_marker"] = INSUFFICIENT_POPULATION_MARKER
        df.loc[in_unresolved, count_col] = None
    violations = validate(df, group_cols=group_cols, count_col=count_col)
    marker_col = f"{count_col}_suppression_marker"
    df = df.rename(columns={"suppression_marker": marker_col}).drop(columns=[TRUE_COUNT_COL], errors="ignore")
    return df, violations


LENGTH_STAT_COLS = ["median_days", "p25_days", "p75_days", "mean_days"]


def _publish_length_stats(df: pd.DataFrame, count_col: str = "count") -> pd.DataFrame:
    """Length-of-time rows as published: no small-cell suppression and no
    n. Every group with at least one person gets its median; one smaller
    than LENGTH_FULL_STATS_MIN_N gets only the median (see config.py)."""
    df = df.copy()
    n = pd.to_numeric(df[count_col], errors="coerce").fillna(0)
    df.loc[n == 0, LENGTH_STAT_COLS] = None
    df.loc[n < LENGTH_FULL_STATS_MIN_N, ["p25_days", "p75_days", "mean_days"]] = None
    return df.drop(columns=[count_col, "suppression_marker"], errors="ignore")


def main():
    start, end = get_export_window()
    print(f"export window: {start} .. {end}")
    as_of = pd.Timestamp(date.today())

    conn = connection.get_connection()
    t = time.time()

    # Client_Demographics: per-person (PersonalID) demographic rollups (the
    # 8 race_* columns, GenderIdentity/GenderAlignment) plus VeteranStatus and
    # LastKnownSubregion — joined into both episode_systemwide and
    # All_Program_Enrollments below, neither of which carries these natively.
    # (LastKnownCity/last_known_city filter temporarily disabled.)
    # Synapse table is singular ("client_demographic"), unlike its Looker
    # view name / the notebook it was ported from — confirmed against
    # INFORMATION_SCHEMA.TABLES directly, not assumed.
    # Narrowed to the columns this pipeline actually reads (full-table
    # SELECT * was the single biggest cost in every run) — GenderExpanded/
    # RaceAndEthnicity_* feed demographics.py's rollups below,
    # VeteranStatus/LastKnownSubregion are merged onto episodes further
    # down. Verify against the live schema (column names/casing) before
    # trusting this in CI — this list comes from static analysis of
    # pipeline/*.py, not a live Synapse check.
    client_demographics = connection.query(
        conn,
        """
        SELECT PersonalID, GenderExpanded,
               RaceAndEthnicity_AIAN, RaceAndEthnicity_Asian, RaceAndEthnicity_Black,
               RaceAndEthnicity_NHPI, RaceAndEthnicity_WC, RaceAndEthnicity_HL, RaceAndEthnicity_MENA,
               VeteranStatus, LastKnownSubregion
        FROM client_demographic
        """,
    )
    t = _checkpoint("fetch client_demographic", t)
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

    # Pull with no date trim for episode_systemwide: return-cohort detection
    # needs to see up to RETURN_WINDOW_DAYS past the window's end, and the
    # length/flow builders trim to the window themselves below.
    # Narrowed to the columns this pipeline actually reads — see the
    # client_demographics query above for the same caveat (static analysis,
    # not a live schema check). ClientUniqueIdentifier deliberately left
    # out: it's only ever mentioned as the reason the fan-out below exists,
    # never read by name.
    all_episodes = connection.query(
        conn,
        """
        SELECT PersonalID, EpisodeID, TimePeriodStartDate, EpisodeStartDate, EpisodeEndDate,
               EpisodeChronicStatus, EpisodeHouseholdType, EpisodeAgeTier,
               EpisodeInflowType, EpisodeOutflowType, LengthOfTimeExperiencingHomelessness,
               AgedOutOfYYA, FlagYYA, LastShelterStatusInTimeframe
        FROM episode_systemwide
        """,
    )
    t = _checkpoint("fetch episode_systemwide", t)
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
    # other builder (length, return cohorts) doesn't need this lookback and
    # keeps using episodes_in_window.
    episodes_with_lookback = _scope_to_window(all_episodes, "TimePeriodStartDate", month_before(start), end)

    # Narrowed to the columns build_capacity.py actually reads — same
    # static-analysis caveat as the queries above.
    # TimePeriodStartDate range pushed into the query — this is the exact
    # same [start, end] bound _scope_to_window below already applied
    # client-side, so Synapse now only ships the rows that bound would have
    # kept anyway, not program_performance_metrics' entire history.
    performance_metrics = connection.query(
        conn,
        f"""
        SELECT ProgramID, TimePeriod, TimePeriodStartDate, TimePeriodEndDate,
               MaxUnitsAvailableDuringTimeframe, EnrolledDuringTimeframe,
               UnitNightsUsedNumerator, UnitNightsAvailableDenominator,
               MaxBedsAvailableDuringTimeframe, ExitedDuringTimeframe, ActiveEnrollmentsInTimeframe,
               BedNightsUsedNumerator, BedNightsAvailableDenominator
        FROM program_performance_metrics
        WHERE TimePeriodStartDate >= '{start.isoformat()}' AND TimePeriodStartDate <= '{end.isoformat()}'
        """,
    )
    t = _checkpoint("fetch program_performance_metrics", t)
    performance_metrics["TimePeriodStartDate"] = pd.to_datetime(performance_metrics["TimePeriodStartDate"])
    performance_metrics["TimePeriodEndDate"] = pd.to_datetime(performance_metrics["TimePeriodEndDate"])
    # Cheap safety net over the SQL filter above, same reasoning as the
    # event_systemwide query's own belt-and-suspenders check — kept rather
    # than removed since it's now filtering an already-small frame.
    performance_metrics = _scope_to_window(performance_metrics, "TimePeriodStartDate", start, end)

    program_attributes = connection.query(conn, "SELECT ProgramID, ProjectTypeCode, Subregion FROM program_attributes")
    t = _checkpoint("fetch program_attributes", t)
    # Synapse stores the human-readable HUD label here, not the numeric code
    # CAPACITY_PROJECT_TYPE_GROUPS is keyed by — see config.py.
    program_attributes["ProjectTypeCode"] = program_attributes["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)

    # All_Program_Enrollments — needed by build_flow_rows/yearly/quarterly to
    # resolve the project_engaged_* dimensions (see build_flow.py's
    # _project_engagement_category). Not date-scoped to window END, or by
    # ProjectStartDate at all: a long-open enrollment that started years
    # earlier must still count as overlapping this window's periods, and
    # _project_engagement_category's own per-period overlap check (run
    # fresh for every month/quarter/year, against that period's own
    # start/end) is what actually decides overlap — this query's WHERE
    # isn't a stand-in for that check. It only drops enrollments that
    # ALREADY EXITED before `start`, the export window's own earliest
    # possible period_start: such an enrollment's ProjectExitDate is always
    # < every period_start that will ever be checked against it, so it
    # fails that per-period overlap check (ProjectExitDate >= period_start)
    # unconditionally, for every period, every time — pre-filtering it here
    # changes none of that check's outcomes, it just skips fetching rows
    # that were always going to fail it.
    enrollments = connection.query(
        conn,
        f"""
        SELECT PersonalID, ProgramID, ProjectStartDate, ProjectExitDate, ProjectTypeCode
        FROM all_program_enrollments
        WHERE ProjectExitDate IS NULL OR ProjectExitDate >= '{start.isoformat()}'
        """,
    )
    t = _checkpoint("fetch all_program_enrollments", t)
    enrollments["ProjectStartDate"] = pd.to_datetime(enrollments["ProjectStartDate"])
    enrollments["ProjectExitDate"] = pd.to_datetime(enrollments["ProjectExitDate"])
    # String, to match PROJECT_ENGAGEMENT_PROGRAM_IDS (project_engaged_ce's CESP filter).
    enrollments["ProgramID"] = enrollments["ProgramID"].astype("string")
    # Same text-label-vs-numeric-code mismatch as program_attributes above.
    enrollments["ProjectTypeCode"] = enrollments["ProjectTypeCode"].map(PROJECT_TYPE_CODE_TEXT_TO_HUD)

    # event_systemwide — needed by every build_*.py module (via
    # period_dimensions.py's _subregion_engagement_category) to resolve the
    # engaged_in_subregion_* dimensions: did a person have a homelessness-
    # indicating event (ClientStatus == "Homeless") at a program located in
    # a given King County subregion, sometime within the period being
    # built. Unlike `enrollments` above, this IS safe to trim both ways in
    # SQL rather than pulling full history and filtering client-side:
    # event_systemwide has one point-in-time EventDate per row (no
    # start/end span, so there's no "started long ago, still open" case an
    # enrollment can have), and every build_*.py module restricts the
    # periods it actually builds to `start` onward (see each one's own
    # `months = [m for m in all_months if window_start is None or m >=
    # window_start]`-shaped filter) — so no period's own period_start is
    # ever earlier than `start`, and an event dated before `start` can
    # therefore never fall inside any period's [period_start, period_end]
    # window regardless of how the per-builder date checks slice it.
    # ClientStatus = 'Homeless' is pushed into the query for the same
    # reason — nothing downstream ever reads a non-"Homeless" row — cutting
    # both filters here means Synapse only ever has to serialize and ship
    # the rows this pipeline can possibly use, instead of this table's
    # entire history.
    # TODO: confirm "event_systemwide" is this table's exact Synapse name
    # (by analogy with episode_systemwide/program_attributes/
    # all_program_enrollments' own naming convention) the same way
    # client_demographic's own name was confirmed against
    # INFORMATION_SCHEMA.TABLES — not yet verified live against Synapse.
    events = connection.query(
        conn,
        f"""
        SELECT PersonalID, ProgramID, EventDate, ClientStatus
        FROM event_systemwide
        WHERE ClientStatus = 'Homeless' AND EventDate >= '{start.isoformat()}'
        """,
    )
    t = _checkpoint("fetch event_systemwide", t)
    events["EventDate"] = pd.to_datetime(events["EventDate"])
    # Cheap safety net over the SQL filter above, not the primary filter
    # anymore — guards against a ClientStatus value Synapse's own string
    # comparison treats as equal (trailing whitespace, case folding, etc.)
    # but pandas' exact-match wouldn't, same "validate at the system
    # boundary" reasoning as the rest of this function's external-data
    # handling.
    events = events[events["ClientStatus"] == "Homeless"]
    # program_attributes.Subregion is a property of the program's own
    # physical location (pre-geocoded, manually maintained — see
    # config.py's SUBREGION_ENGAGEMENT_GROUPS comment), joined onto each
    # event by ProgramID the same way build_capacity.py already joins
    # program_attributes onto performance_metrics.
    events = events.merge(program_attributes[["ProgramID", "Subregion"]], on="ProgramID", how="left")
    t = time.time()

    # Shared by build_flow_yearly_rows/build_flow_quarterly_rows below — see
    # build_month_population_cache's own docstring for why this is built
    # once here rather than each of those two independently recomputing
    # filter_population per (month, pop_label) pair.
    month_pop_cache = build_month_population_cache(episodes_with_lookback)
    t = _checkpoint("build_month_population_cache", t)

    # --- dashboard_flow_monthly ---
    flow_df = build_flow_rows(episodes_with_lookback, enrollments, events, window_start=pd.Timestamp(start))
    flow_df = _drop_overlap_not_included(flow_df)
    flow_df, flow_deceased_df = _split_deceased(flow_df)
    t = _checkpoint("build_flow_rows", t)

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
    # How many of each inactive count are deceased, as a band (see
    # suppression.apply_deceased_bands). Needs the inactive cells' final markers.
    flow_deceased_df = apply_deceased_bands(flow_deceased_df, flow_df, period_col="month")
    flow_violations = validate(flow_df, group_cols=["month", "population_segment", "dimension", "flow_type"])
    flow_violations += validate_deceased_bands(flow_deceased_df, flow_df, period_col="month")
    flow_violations += validate_crosstab(flow_df, group_cols=["month", "population_segment", "dimension", "category"])
    flow_violations += validate_sankey_marginal(flow_df, group_cols=["month", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS)
    t = _checkpoint("flow_df suppression+validate", t)

    # --- dashboard_flow_yearly (true distinct-person experienced_homelessness
    # and indiv_* partition per year — see build_flow_yearly_rows for why
    # these can't just be summed from dashboard_flow_monthly's per-month
    # figures) ---
    flow_yearly_df = build_flow_yearly_rows(episodes_with_lookback, enrollments, events, month_pop_cache, window_start=pd.Timestamp(start))
    t = _checkpoint("build_flow_yearly_rows", t)
    flow_yearly_df, flow_yearly_deceased_df, flow_yearly_violations = _suppress_flow_yearly(flow_yearly_df)
    t = _checkpoint("flow_yearly_df suppression+validate", t)

    # --- dashboard_flow_ytd_prior / dashboard_length_headline_ytd_prior ---
    # The current year is partial (through `end`'s month), so comparing its
    # year-to-date row against the prior FULL year would always read as a
    # drop. These hold the prior year capped to the same months instead
    # (e.g. Jan-Oct 2025 next to Jan-Oct 2026), for the dashboard's
    # full-year trend pills. Empty when the current year is complete (a
    # December `end`) or the prior year falls outside the window — the
    # frontend then just compares full years as before.
    ytd_year, ytd_through = end.year - 1, end.month
    has_ytd_prior = ytd_through < 12 and ytd_year >= start.year
    flow_ytd_prior_df = flow_ytd_prior_deceased_df = None
    flow_ytd_prior_violations: list[str] = []
    length_headline_ytd_prior_df = None
    if has_ytd_prior:
        flow_ytd_prior_df = build_flow_yearly_rows(
            episodes_with_lookback, enrollments, events, month_pop_cache,
            window_start=pd.Timestamp(start), only_year=ytd_year, through_month=ytd_through,
        )
        flow_ytd_prior_df, flow_ytd_prior_deceased_df, flow_ytd_prior_violations = _suppress_flow_yearly(flow_ytd_prior_df)
        length_headline_ytd_prior_df = build_length_headline_rows(
            episodes_with_lookback, enrollments, events,
            window_start=pd.Timestamp(start), only_year=ytd_year, through_month=ytd_through,
        )
        length_headline_ytd_prior_df = _publish_length_stats(_drop_overlap_not_included(length_headline_ytd_prior_df))
        t = _checkpoint(f"ytd_prior ({ytd_year} Jan-month {ytd_through}) build+suppression", t)

    # --- dashboard_flow_quarterly (drill-down granularity for OutflowSection's
    # pills — same "can't be summed from monthly cells" rationale as yearly,
    # see build_flow_quarterly_rows) ---
    flow_quarterly_df = build_flow_quarterly_rows(episodes_with_lookback, enrollments, events, month_pop_cache, window_start=pd.Timestamp(start))
    flow_quarterly_df = _drop_overlap_not_included(flow_quarterly_df)
    flow_quarterly_df, flow_quarterly_deceased_df = _split_deceased(flow_quarterly_df)
    t = _checkpoint("build_flow_quarterly_rows", t)
    flow_quarterly_df = apply_full_suppression_pipeline(
        flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"]
    )
    flow_quarterly_df = apply_crosstab_secondary_suppression(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])
    flow_quarterly_df = apply_sankey_marginal_suppression(
        flow_quarterly_df, group_cols=["quarter", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS
    )
    flow_quarterly_df = apply_insufficient_population_fallback(
        flow_quarterly_df,
        period_col="quarter",
        main_group_cols=["quarter", "population_segment", "dimension", "flow_type"],
        crosstab_group_cols=["quarter", "population_segment", "dimension", "category"],
        sankey_bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS,
    )
    # How many of each inactive count are deceased, as a band (see
    # suppression.apply_deceased_bands). Needs the inactive cells' final markers.
    flow_quarterly_deceased_df = apply_deceased_bands(flow_quarterly_deceased_df, flow_quarterly_df, period_col="quarter")
    flow_quarterly_violations = validate(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "flow_type"])
    flow_quarterly_violations += validate_deceased_bands(flow_quarterly_deceased_df, flow_quarterly_df, period_col="quarter")
    flow_quarterly_violations += validate_crosstab(flow_quarterly_df, group_cols=["quarter", "population_segment", "dimension", "category"])
    flow_quarterly_violations += validate_sankey_marginal(
        flow_quarterly_df, group_cols=["quarter", "population_segment"], bucket_flow_type_groups=SANKEY_BUCKET_FLOW_TYPE_GROUPS
    )
    t = _checkpoint("flow_quarterly_df suppression+validate", t)

    # --- dashboard_length_* tables ---
    # Medians of days experiencing homelessness never name how many people
    # are in a group, so these skip small-cell suppression entirely: every
    # group with at least one person is published, n itself never is, and
    # groups under LENGTH_FULL_STATS_MIN_N get only their median (see
    # _publish_length_stats).
    length_df = build_length_rows(episodes_in_window, enrollments, events)
    length_df = _publish_length_stats(_drop_overlap_not_included(length_df))
    t = _checkpoint("build_length_rows", t)

    # dashboard_length_by_exit_monthly: split by permanently_housed/
    # inactive/aged_out, deceased excluded (see build_length_by_exit.py's
    # module docstring). episodes_with_lookback + window_start, not
    # episodes_in_window: aged-out detection needs a true prior_month for
    # the window's own first published month, same reason build_flow_rows
    # needs it.
    length_by_exit_df = build_length_by_exit_rows(episodes_with_lookback, enrollments, events, window_start=pd.Timestamp(start))
    length_by_exit_df = _publish_length_stats(_drop_overlap_not_included(length_by_exit_df))
    t = _checkpoint("build_length_by_exit_rows", t)

    # dashboard_length_headline_yearly/_monthly/_quarterly: single pooled
    # median (deceased included) — see build_length_by_exit.py's own
    # docstring for exactly what this pools. Monthly/quarterly power
    # LengthSection's headline KPI card when a reader drills into a
    # specific month/quarter.
    length_headline_df = build_length_headline_rows(episodes_with_lookback, enrollments, events, window_start=pd.Timestamp(start))
    length_headline_df = _publish_length_stats(_drop_overlap_not_included(length_headline_df))
    t = _checkpoint("build_length_headline_rows", t)
    length_headline_monthly_df = build_length_headline_monthly_rows(episodes_with_lookback, enrollments, events, window_start=pd.Timestamp(start))
    length_headline_monthly_df = _publish_length_stats(_drop_overlap_not_included(length_headline_monthly_df))
    t = _checkpoint("build_length_headline_monthly_rows", t)
    length_headline_quarterly_df = build_length_headline_quarterly_rows(episodes_with_lookback, enrollments, events, window_start=pd.Timestamp(start))
    length_headline_quarterly_df = _publish_length_stats(_drop_overlap_not_included(length_headline_quarterly_df))
    t = _checkpoint("build_length_headline_quarterly_rows", t)

    # --- dashboard_return_cohorts ---
    return_df = build_return_cohort_rows(episodes_in_window, all_episodes, enrollments, events, as_of=as_of)
    return_df = _drop_overlap_not_included(return_df)
    t = _checkpoint("build_return_cohort_rows", t)
    return_df = return_df.rename(columns={"n_exited": "count"})
    return_df = apply_full_suppression_pipeline(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_df = apply_insufficient_population_fallback(
        return_df,
        period_col="exit_quarter",
        main_group_cols=["exit_quarter", "population_segment", "dimension"],
        crosstab_group_cols=[],
        count_col="count",
    )
    return_violations = validate(return_df, group_cols=["exit_quarter", "population_segment", "dimension"], count_col="count")
    return_df = return_df.rename(columns={"count": "n_exited"})
    # n_returned/pct_returned on rows hidden above are nulled inside
    # apply_return_count_suppression, which needs their true n_returned
    # first: a hidden row's n_returned can still be calculated from the
    # other categories, so it isn't automatically protected.
    # n_exited being above threshold doesn't mean n_returned is — a cohort
    # can have plenty of exits but only a handful who returned. Suppressed
    # independently (see apply_return_count_suppression) so a well-populated
    # row isn't hidden entirely just because this one derived count is
    # small; the frontend shows the exited total with the return split
    # marked as withheld instead.
    return_df, return_count_violations = apply_return_count_suppression(
        return_df,
        group_cols=["exit_quarter", "population_segment", "dimension"],
        count_col="n_returned",
        marker_col="return_suppression_marker",
        extra_cols=["pct_returned"],
    )
    return_violations += return_count_violations
    t = _checkpoint("return_df suppression+validate", t)

    # --- dashboard_capacity_monthly / _quarterly / _yearly (aggregate
    # inventory data, not person-level — units_in_system/beds_in_system/
    # pct_utilization/bed_pct_utilization never get suppressed — but
    # enrolled/exited/active ARE real household headcounts, and the
    # subregion breakdown below can make one small enough to need the same
    # primary/secondary protection every
    # person-level table gets; see _suppress_capacity_household_count) ---
    capacity_df = build_capacity_rows(performance_metrics, program_attributes, as_of=as_of)
    capacity_quarterly_df = build_capacity_quarterly_rows(performance_metrics, program_attributes, as_of=as_of)
    # Yearly deliberately doesn't get this treatment — the current
    # (incomplete) year is intentionally included there, labeled
    # "year to date" by the frontend's existing Year selector, unlike
    # the quarterly/monthly charts which should only ever show complete
    # periods.
    capacity_yearly_df = build_capacity_yearly_rows(performance_metrics, program_attributes)

    capacity_df, capacity_violations = _suppress_capacity_household_count(capacity_df, "month", "enrolled")
    capacity_df.loc[capacity_df["enrolled_suppression_marker"].notna(), "throughput_hh_per_unit"] = None

    capacity_quarterly_df, capacity_quarterly_violations = _suppress_capacity_household_count(
        capacity_quarterly_df, "quarter", "enrolled"
    )
    capacity_quarterly_df.loc[capacity_quarterly_df["enrolled_suppression_marker"].notna(), "throughput_hh_per_unit"] = None

    capacity_yearly_df, capacity_yearly_enrolled_violations = _suppress_capacity_household_count(capacity_yearly_df, "year", "enrolled")
    capacity_yearly_df, capacity_yearly_exited_violations = _suppress_capacity_household_count(capacity_yearly_df, "year", "exited")
    capacity_yearly_df, capacity_yearly_active_violations = _suppress_capacity_household_count(capacity_yearly_df, "year", "active")
    capacity_yearly_violations = capacity_yearly_enrolled_violations + capacity_yearly_exited_violations + capacity_yearly_active_violations
    # households_per_unit/people_per_bed/pct_exited are all derived FROM
    # active (and pct_exited from exited too — see build_capacity.py's
    # _grouped_yearly_metrics) — nulled alongside whichever headcount(s)
    # they're built from, same reasoning as throughput_hh_per_unit above,
    # so neither ratio hands a suppressed headcount back via the
    # units_in_system/beds_in_system/active figure published right next to it.
    capacity_yearly_df.loc[capacity_yearly_df["active_suppression_marker"].notna(), "households_per_unit"] = None
    capacity_yearly_df.loc[capacity_yearly_df["active_suppression_marker"].notna(), "people_per_bed"] = None
    capacity_yearly_df.loc[
        capacity_yearly_df["exited_suppression_marker"].notna() | capacity_yearly_df["active_suppression_marker"].notna(),
        "pct_exited",
    ] = None
    t = _checkpoint("build_capacity_rows/_quarterly/_yearly + suppression", t)

    all_violations = (
        flow_violations
        + flow_yearly_violations
        + flow_ytd_prior_violations
        + flow_quarterly_violations
        + return_violations
        + capacity_violations
        + capacity_quarterly_violations
        + capacity_yearly_violations
    )
    if all_violations:
        print("SUPPRESSION VALIDATION FAILED:", file=sys.stderr)
        for v in all_violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    # inflow_bucket/outflow_bucket only exist to give
    # apply_crosstab_secondary_suppression a clean grouping key — internal,
    # like TRUE_COUNT_COL, never written to the exported JSON.
    flow_df = pd.concat([flow_df, flow_deceased_df], ignore_index=True)
    flow_yearly_df = pd.concat([flow_yearly_df, flow_yearly_deceased_df], ignore_index=True)
    flow_quarterly_df = pd.concat([flow_quarterly_df, flow_quarterly_deceased_df], ignore_index=True)
    flow_df = flow_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")
    flow_yearly_df = flow_yearly_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")
    flow_quarterly_df = flow_quarterly_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")

    _write_monthly_flow_split(_to_json_records(flow_df, ["month"]))
    _write("dashboard_flow_yearly.json", _to_json_records(flow_yearly_df, []))
    _write_quarterly_flow_split(_to_json_records(flow_quarterly_df, ["quarter"]))
    if has_ytd_prior:
        flow_ytd_prior_df = pd.concat([flow_ytd_prior_df, flow_ytd_prior_deceased_df], ignore_index=True)
        flow_ytd_prior_df = flow_ytd_prior_df.drop(columns=["inflow_bucket", "outflow_bucket"], errors="ignore")
        _write("dashboard_flow_ytd_prior.json", _to_json_records(flow_ytd_prior_df.assign(through_month=ytd_through), []))
        _write(
            "dashboard_length_headline_ytd_prior.json",
            _to_json_records(length_headline_ytd_prior_df.assign(through_month=ytd_through), []),
        )
    else:
        _write("dashboard_flow_ytd_prior.json", [])
        _write("dashboard_length_headline_ytd_prior.json", [])
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
