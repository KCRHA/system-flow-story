"""Builds dashboard_return_cohorts (Table 2b): one row per (exit_quarter,
population_segment, dimension, category). Built entirely from
episode_systemwide — a permanently-housed episode outflow starts the clock;
"returned" means the same person has a later episode, starting within
RETURN_WINDOW_DAYS (6 months) of that exit, whose EpisodeInflowType
resolves to "Return from Housed". That inflow classification itself comes
from a broader 730-day gap threshold upstream (episode_systemwide's own
determine_inflow_type()), so every return within our narrower 6-month
window is guaranteed to already carry that label — see config.py.
"""
from datetime import timedelta

import pandas as pd

from .config import DIMENSION_COLUMNS, POPULATION_SEGMENTS, PROJECT_ENGAGEMENT_DIMENSIONS, RETURN_WINDOW_DAYS
from .period_dimensions import (
    _BINARY_CATEGORIES,
    EXTENDED_DIMENSIONS,
    PERIOD_AGGREGATE_CATEGORY_DIMENSIONS,
    _group_enrollments_by_dimension,
    _project_engagement_category,
    _unsheltered_in_period_category,
)
from .population import filter_population


def _all_categories(df: pd.DataFrame, dimension: str) -> list:
    """Every category value that appears anywhere in `df` for this
    dimension — every exit_month/segment slice is reindexed against this
    full set so a category with zero exits that slice still emits an
    explicit n_exited=0 row instead of being silently absent (mirrors the
    identical fix in build_flow.py/build_length.py).

    unsheltered_in_period/project_engaged_* are fixed Included/Not Included
    pairs, not data-derived like every other branch here — see
    build_length.py's identical comment on its own _all_categories."""
    if dimension == "overall":
        return ["Overall"]
    if dimension in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS:
        return _BINARY_CATEGORIES
    return sorted(df[DIMENSION_COLUMNS[dimension]].dropna().unique().tolist())


def build_return_cohort_rows(
    episodes_in_window: pd.DataFrame, all_episodes: pd.DataFrame, enrollments: pd.DataFrame, as_of: pd.Timestamp
) -> pd.DataFrame:
    """
    episodes_in_window: episode_systemwide rows whose exit month falls in the
      export window (last 5 completed years + completed months of this year).
      Carries every monthly row an episode spans, not just exit rows — also
      used below to resolve unsheltered_in_period across each exit cohort's
      whole quarter, not just its members' own exit rows.
    all_episodes: episode_systemwide with no date trim — needed because a
      return can occur up to RETURN_WINDOW_DAYS after an exit near the end of
      the export window, past what that window alone would contain.
    enrollments: raw All_Program_Enrollments rows, used only to resolve the
      project_engaged_* dimensions (see _project_engagement_category) — same
      contract as build_length.py's build_length_rows.
    as_of: "today" for window_complete purposes (a cohort's window is only
      complete once RETURN_WINDOW_DAYS have fully elapsed since exit_quarter
      ended — the latest possible exit date in the quarter — so every exit
      in the quarter has had the full window to show a return).
    """
    # EpisodeOutflowType is a per-*episode* label stamped on every monthly
    # row an episode spans (see Episode_Systemwide notebook's
    # process_episode()), not a per-month "exited this month" flag —
    # filtering on it alone would attribute a single exit to every month of
    # the episode that preceded it, not just the month it actually
    # happened. Restrict to each episode's own closing row (same fix as
    # build_flow.py's outflow rows / build_length.py's active population).
    # This check stays month-precise regardless of the quarter grouping
    # below — it's identifying the one true exit event row, not aggregating.
    end_period = episodes_in_window["EpisodeEndDate"].dt.to_period("M")
    time_period = episodes_in_window["TimePeriodStartDate"].dt.to_period("M")
    is_exit_row = (time_period == end_period) & (episodes_in_window["EpisodeOutflowType"] == "Permanently Housed")
    exits = episodes_in_window[is_exit_row].copy()
    exits["exit_quarter"] = exits["TimePeriodStartDate"].dt.to_period("Q").dt.start_time
    returns_by_person = (
        all_episodes[all_episodes["EpisodeInflowType"] == "Return from Housed"]
        .groupby("PersonalID")["EpisodeStartDate"]
        .apply(list)
        .to_dict()
    )

    rows: list = []
    exit_quarters = sorted(exits["exit_quarter"].unique())
    all_categories = {dimension: _all_categories(exits, dimension) for dimension in EXTENDED_DIMENSIONS}
    # ProjectTypeCode-filtered once per project_engaged_* dimension, reused
    # across every quarter below — see _group_enrollments_by_dimension.
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    for exit_quarter in exit_quarters:
        quarter_df = exits[exits["exit_quarter"] == exit_quarter]
        quarter_start = pd.Period(exit_quarter, freq="Q").start_time
        # Anchored to the quarter's end, since that's the latest date any
        # exit in this quarter could have happened — anchoring to the start
        # (as the old monthly version did) would call a quarter complete up
        # to ~3 months before its late exits actually clear the window.
        quarter_end = pd.Period(exit_quarter, freq="Q").end_time.normalize()
        window_complete = (pd.Timestamp(as_of) - quarter_end).days >= RETURN_WINDOW_DAYS

        # unsheltered_in_period/project_engaged_* are resolved fresh per
        # quarter (an OR across every row/enrollment within it — see
        # period_dimensions.py) — but "the period" here is this cohort's
        # whole exit quarter, not just each person's own single exit row,
        # so someone unsheltered earlier in the quarter but sheltered by
        # their exit month still reads as Included, same as the question
        # length/flow already ask over a month. episodes_in_window already
        # carries every monthly row (is_exit_row above only narrowed
        # `exits`, not the source frame), so quarter_person_rows below is
        # every row this cohort's own members have within the quarter.
        quarter_cohort_ids = quarter_df["PersonalID"].unique()
        quarter_person_rows = episodes_in_window[
            episodes_in_window["PersonalID"].isin(quarter_cohort_ids)
            & (episodes_in_window["TimePeriodStartDate"] >= quarter_start)
            & (episodes_in_window["TimePeriodStartDate"] <= quarter_end)
        ]
        period_category = {
            "unsheltered_in_period": _unsheltered_in_period_category(quarter_person_rows),
            **{
                dim: _project_engagement_category(quarter_person_rows, group_enrollments[dim], quarter_start, quarter_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }
        quarter_df = quarter_df.assign(
            **{
                DIMENSION_COLUMNS[dim]: quarter_df["PersonalID"].map(period_category[dim])
                for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS
            }
        )

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_df = filter_population(quarter_df, pop_label, exit_quarter)

            def _returned(personal_id, exit_date):
                for return_date in returns_by_person.get(personal_id, []):
                    if pd.Timestamp(exit_date) < pd.Timestamp(return_date) <= pd.Timestamp(exit_date) + timedelta(days=RETURN_WINDOW_DAYS):
                        return True
                return False

            pop_df = pop_df.assign(
                _returned=[
                    _returned(pid, exit_date)
                    for pid, exit_date in zip(pop_df["PersonalID"], pop_df["EpisodeEndDate"])
                ]
            )

            for dimension in EXTENDED_DIMENSIONS:
                if dimension == "overall":
                    groups = {"Overall": pop_df}
                else:
                    category_col = DIMENSION_COLUMNS[dimension]
                    groups = {name: g for name, g in pop_df.groupby(category_col)}

                for category in all_categories[dimension]:
                    group = groups.get(category)
                    n_exited = len(group) if group is not None else 0
                    n_returned = int(group["_returned"].sum()) if group is not None else 0
                    rows.append(
                        {
                            "exit_quarter": exit_quarter,
                            "population_segment": segment_key,
                            "dimension": dimension,
                            "category": category,
                            "n_exited": n_exited,
                            "n_returned": n_returned,
                            "pct_returned": (n_returned / n_exited) if (n_exited and window_complete) else None,
                            "window_complete": window_complete,
                        }
                    )

    return pd.DataFrame(rows)
