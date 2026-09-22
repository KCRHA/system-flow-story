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

from .config import DIMENSIONS, DIMENSION_COLUMNS, POPULATION_SEGMENTS, RETURN_WINDOW_DAYS
from .population import filter_population


def _all_categories(df: pd.DataFrame, dimension: str) -> list:
    """Every category value that appears anywhere in `df` for this
    dimension — every exit_month/segment slice is reindexed against this
    full set so a category with zero exits that slice still emits an
    explicit n_exited=0 row instead of being silently absent (mirrors the
    identical fix in build_flow.py/build_length.py)."""
    if dimension == "overall":
        return ["Overall"]
    return sorted(df[DIMENSION_COLUMNS[dimension]].dropna().unique().tolist())


def build_return_cohort_rows(episodes_in_window: pd.DataFrame, all_episodes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """
    episodes_in_window: episode_systemwide rows whose exit month falls in the
      export window (last 5 completed years + completed months of this year).
    all_episodes: episode_systemwide with no date trim — needed because a
      return can occur up to RETURN_WINDOW_DAYS after an exit near the end of
      the export window, past what that window alone would contain.
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
    all_categories = {dimension: _all_categories(exits, dimension) for dimension in DIMENSIONS}

    for exit_quarter in exit_quarters:
        quarter_df = exits[exits["exit_quarter"] == exit_quarter]
        # Anchored to the quarter's end, since that's the latest date any
        # exit in this quarter could have happened — anchoring to the start
        # (as the old monthly version did) would call a quarter complete up
        # to ~3 months before its late exits actually clear the window.
        quarter_end = pd.Period(exit_quarter, freq="Q").end_time.normalize()
        window_complete = (pd.Timestamp(as_of) - quarter_end).days >= RETURN_WINDOW_DAYS

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

            for dimension in DIMENSIONS:
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
