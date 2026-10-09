"""unsheltered_in_period / project_engaged_* dimension resolution, shared by
every build_*.py module that disaggregates by dimension — not just
build_flow.py (originally the only consumer; build_length.py and
build_length_by_exit.py now use this too, so people/their length of time
homeless can be broken out by these same two categories).

These two can't live in config.DIMENSIONS alongside the rest (see
config.py's own comment on DIMENSIONS/PROJECT_ENGAGEMENT_GROUPS): every
other dimension in that list is a standing column on episode_systemwide/
All_Program_Enrollments, read with a single groupby. These aren't —
"did this person experience unsheltered homelessness" or "was this person
engaged with project type X" at any point in the period being built (month/
quarter/year) is itself an inherently period-level question, an OR across
every row/enrollment a person has in that period, not a fixed per-row
value — so each consuming build_*.py module must resolve a fresh
PersonalID -> category column fresh per period it builds, from whichever of
its own two source frames (episode_systemwide rows for unsheltered_in_period,
All_Program_Enrollments rows for project_engaged_*) is in scope, via
_unsheltered_in_period_category/_project_engagement_category below.
"""
import numpy as np
import pandas as pd

from .config import DIMENSIONS, PROJECT_ENGAGEMENT_DIMENSIONS, PROJECT_ENGAGEMENT_GROUPS

_BINARY_CATEGORIES = ["Included", "Not Included"]

# PERIOD_AGGREGATE_CATEGORY_DIMENSIONS layered on top of config.DIMENSIONS —
# every build_*.py module that wants this breakdown uses EXTENDED_DIMENSIONS
# in its own per-dimension loops instead of plain DIMENSIONS.
PERIOD_AGGREGATE_CATEGORY_DIMENSIONS = ["unsheltered_in_period", *PROJECT_ENGAGEMENT_DIMENSIONS]
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
    _project_engagement_category does."""
    return {dim: enrollments[enrollments["ProjectTypeCode"].isin(codes)] for dim, codes in PROJECT_ENGAGEMENT_GROUPS.items()}
