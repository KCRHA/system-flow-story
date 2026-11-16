"""unsheltered_in_period / project_engaged_* / engaged_in_subregion_*
dimension resolution, shared by every build_*.py module that disaggregates
by dimension — not just build_flow.py (originally the only consumer;
build_length.py, build_length_by_exit.py, and build_return_cohorts.py now
use this too, so people/their length of time homeless/their return-to-
homelessness status can be broken out by these same categories).

These can't live in config.DIMENSIONS alongside the rest (see config.py's
own comment on DIMENSIONS/PROJECT_ENGAGEMENT_GROUPS): every other dimension
in that list is a standing column on episode_systemwide/All_Program_
Enrollments, read with a single groupby. These aren't — "did this person
experience unsheltered homelessness," "was this person engaged with project
type X," or "did this person have a qualifying homelessness event in
subregion Y" at any point in the period being built (month/quarter/year) is
itself an inherently period-level question, an OR across every row/
enrollment/event a person has in that period, not a fixed per-row value —
so each consuming build_*.py module must resolve a fresh PersonalID ->
category column fresh per period it builds, from whichever of its own
source frames (episode_systemwide rows for unsheltered_in_period,
All_Program_Enrollments rows for project_engaged_*, event_systemwide rows
for engaged_in_subregion_*) is in scope, via
_unsheltered_in_period_category/_project_engagement_category/
_subregion_engagement_category below.
"""
import numpy as np
import pandas as pd

from .config import (
    DIMENSIONS,
    HOUSEHOLD_TYPE_DIMENSIONS,
    HOUSEHOLD_TYPE_GROUPS,
    PROJECT_ENGAGEMENT_DIMENSIONS,
    PROJECT_ENGAGEMENT_PROGRAM_IDS,
    PROJECT_ENGAGEMENT_GROUPS,
    SUBREGION_ENGAGEMENT_DIMENSIONS,
    SUBREGION_ENGAGEMENT_GROUPS,
)

_BINARY_CATEGORIES = ["Included", "Not Included"]

# PERIOD_AGGREGATE_CATEGORY_DIMENSIONS layered on top of config.DIMENSIONS —
# every build_*.py module that wants this breakdown uses EXTENDED_DIMENSIONS
# in its own per-dimension loops instead of plain DIMENSIONS.
PERIOD_AGGREGATE_CATEGORY_DIMENSIONS = [
    "unsheltered_in_period",
    *PROJECT_ENGAGEMENT_DIMENSIONS,
    *SUBREGION_ENGAGEMENT_DIMENSIONS,
    *HOUSEHOLD_TYPE_DIMENSIONS,
]
EXTENDED_DIMENSIONS = [*DIMENSIONS, *PERIOD_AGGREGATE_CATEGORY_DIMENSIONS]


def _unsheltered_in_period_category(period_df: pd.DataFrame) -> pd.Series:
    """PersonalID -> "Included"/"Not Included", true if ANY of the person's
    rows within `period_df` (this month's, quarter's, or year's own episode
    rows — unfiltered by population) has LastShelterStatusInTimeframe ==
    "Unsheltered". A person with no recorded shelter status at all in the
    period (about 1% of active_df most months — episode_systemwide can
    carry a null LastShelterStatusInTimeframe when no ClientShelterStatus
    event has landed yet) simply isn't Unsheltered by this definition and
    falls to "Not Included", the same as anyone confirmed Sheltered/
    Temporarily Housed — a deliberate choice (not every other dimension's
    explicit-"Unknown"-bucket pattern) so this stays a clean two-category
    partition without a third bucket to suppress and hide from the
    frontend."""
    ids = period_df["PersonalID"].unique()
    unsheltered_ids = set(period_df.loc[period_df["LastShelterStatusInTimeframe"] == "Unsheltered", "PersonalID"])
    return pd.Series(np.where(pd.Index(ids).isin(unsheltered_ids), "Included", "Not Included"), index=ids)


def _household_type_category(period_df: pd.DataFrame, dimension: str) -> pd.Series:
    """PersonalID -> "Included"/"Not Included" for one household_type_*
    dimension, true if ANY of the person's rows within `period_df` has that
    dimension's EpisodeHouseholdType (config.py's HOUSEHOLD_TYPE_GROUPS).
    Same OR-across-the-period contract as _unsheltered_in_period_category,
    so the categories overlap for anyone whose household type changed
    between episodes in the period."""
    ids = period_df["PersonalID"].unique()
    matched_ids = set(period_df.loc[period_df["EpisodeHouseholdType"] == HOUSEHOLD_TYPE_GROUPS[dimension], "PersonalID"])
    return pd.Series(np.where(pd.Index(ids).isin(matched_ids), "Included", "Not Included"), index=ids)


def household_type_categories(period_df: pd.DataFrame) -> dict:
    """Every household_type_* dimension's category series for one period."""
    return {dim: _household_type_category(period_df, dim) for dim in HOUSEHOLD_TYPE_DIMENSIONS}


def _project_engagement_category(period_df: pd.DataFrame, group_enrollments: pd.DataFrame, period_start, period_end) -> pd.Series:
    """PersonalID -> "Included"/"Not Included" for one project_engaged_*
    dimension, true if the person has ANY All_Program_Enrollments row in
    `group_enrollments` (already restricted to that dimension's HUD
    ProjectTypeCodes — see config.py's PROJECT_ENGAGEMENT_GROUPS) whose
    [ProjectStartDate, ProjectExitDate] span overlaps ANY part of
    [period_start, period_end] — a null ProjectExitDate (still enrolled)
    always counts as overlapping. Same OR-across-the-period contract as
    _unsheltered_in_period_category, just resolved against enrollment-level
    project type instead of episode_systemwide's own per-row shelter
    status, since project type has no episode_systemwide equivalent at all.

    `ids` (the population this gets reindexed against) comes from
    `period_df`, same as _unsheltered_in_period_category — every
    episode_systemwide PersonalID active/inflowing/outflowing this period,
    not `group_enrollments`' own PersonalIDs, so someone with zero matching
    enrollments still gets an explicit "Not Included" row rather than being
    silently absent."""
    ids = period_df["PersonalID"].unique()
    overlapping = group_enrollments[
        (group_enrollments["ProjectStartDate"] <= period_end)
        & (group_enrollments["ProjectExitDate"].isna() | (group_enrollments["ProjectExitDate"] >= period_start))
    ]
    engaged_ids = set(overlapping["PersonalID"])
    return pd.Series(np.where(pd.Index(ids).isin(engaged_ids), "Included", "Not Included"), index=ids)


def _group_enrollments_by_dimension(enrollments: pd.DataFrame) -> dict:
    """One {dimension: pre-filtered enrollments} entry per
    PROJECT_ENGAGEMENT_GROUPS dimension, computed once per builder call (not
    per period) since the ProjectTypeCode filter itself doesn't depend on
    which period is being built — only the date-overlap check in
    _project_engagement_category does. Dimensions in
    PROJECT_ENGAGEMENT_PROGRAM_IDS are further limited to those ProgramIDs."""
    groups = {}
    for dim, codes in PROJECT_ENGAGEMENT_GROUPS.items():
        subset = enrollments[enrollments["ProjectTypeCode"].isin(codes)]
        if dim in PROJECT_ENGAGEMENT_PROGRAM_IDS:
            subset = subset[subset["ProgramID"].isin(PROJECT_ENGAGEMENT_PROGRAM_IDS[dim])]
        groups[dim] = subset
    return groups


def _subregion_engagement_category(period_df: pd.DataFrame, group_events: tuple, period_start, period_end) -> pd.Series:
    """PersonalID -> "Included"/"Not Included" for one engaged_in_subregion_*
    dimension, true if the person has ANY event_systemwide row in
    `group_events` (already restricted to ClientStatus == "Homeless" and
    this dimension's Subregion value — see config.py's
    SUBREGION_ENGAGEMENT_GROUPS) whose EventDate falls anywhere within
    [period_start, period_end]. Same OR-across-the-period contract as
    _project_engagement_category, just resolved against a single-date event
    log instead of an enrollment date span — event_systemwide has no
    start/end span, only one EventDate per row, so there's no null-exit-date
    "still open" case to handle the way _project_engagement_category does.

    `group_events` is the (event_dates, event_ids) pair _group_events_by_
    subregion below hands back, EventDate-sorted — this is called once per
    (period, dimension) across every build_*.py module (thousands of calls
    for a multi-year export window), so instead of rescanning every one of
    that dimension's events with a boolean mask each time, this binary-
    searches the sorted dates for the [period_start, period_end] slice
    boundaries and takes just that slice's PersonalIDs. Same matched rows as
    the old `(dates >= period_start) & (dates <= period_end)` mask, just
    O(log n + k) instead of O(n) per call.

    `ids` (the population this gets reindexed against) comes from
    `period_df`, same as _unsheltered_in_period_category/
    _project_engagement_category — every episode_systemwide PersonalID
    active/inflowing/outflowing this period, not `group_events`' own
    PersonalIDs, so someone with zero matching events still gets an explicit
    "Not Included" row rather than being silently absent."""
    ids = period_df["PersonalID"].unique()
    event_dates, event_ids = group_events
    lo = np.searchsorted(event_dates, pd.Timestamp(period_start).to_datetime64(), side="left")
    hi = np.searchsorted(event_dates, pd.Timestamp(period_end).to_datetime64(), side="right")
    engaged_ids = set(event_ids[lo:hi])
    return pd.Series(np.where(pd.Index(ids).isin(engaged_ids), "Included", "Not Included"), index=ids)


def _group_events_by_subregion(events: pd.DataFrame) -> dict:
    """One {dimension: (event_dates, event_ids)} entry per
    SUBREGION_ENGAGEMENT_GROUPS dimension, computed once per builder call
    (not per period) since the Subregion filter itself doesn't depend on
    which period is being built — only the date check in
    _subregion_engagement_category does. `events` must already be filtered
    to ClientStatus == "Homeless" and joined to program_attributes.Subregion
    via ProgramID — see export.py.

    Each dimension's events are collapsed to one row per (PersonalID,
    calendar month) before sorting — every period boundary
    _subregion_engagement_category is ever called with, across every
    build_*.py module, is month-aligned (a month's own start/MonthEnd, or a
    quarter's/year's first month's start to its last month's MonthEnd — see
    that function's own callers), so "does this person have >=1 qualifying
    event in this subregion during month M" is exactly what any
    [period_start, period_end] overlap check actually needs. A person with
    many events in the same subregion the same month (daily shelter
    check-ins, repeat outreach contacts, etc.) collapses to a single row
    here — same engaged/not-engaged answer either way, but a much smaller
    array for _subregion_engagement_category to binary-search when a
    subregion/month combination has heavy repeat-event volume.

    Each dimension's (now deduplicated) events are also sorted by EventDate
    here (once), so _subregion_engagement_category can binary-search the
    per-period window instead of rescanning the full (unbounded, all-
    history) events frame on every call — see that function's own
    docstring."""
    groups = {}
    for dim, subregion in SUBREGION_ENGAGEMENT_GROUPS.items():
        subset = events.loc[events["Subregion"] == subregion, ["EventDate", "PersonalID"]]
        months = subset["EventDate"].to_numpy().astype("datetime64[M]").astype(subset["EventDate"].to_numpy().dtype)
        dedup = pd.DataFrame({"EventDate": months, "PersonalID": subset["PersonalID"].to_numpy()}).drop_duplicates()
        dedup = dedup.sort_values("EventDate")
        groups[dim] = (dedup["EventDate"].to_numpy(), dedup["PersonalID"].to_numpy())
    return groups
