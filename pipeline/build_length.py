"""Builds dashboard_length_monthly: distribution stats (median/p25/p75/mean)
for length of time homeless among people active in a given month, computed
from episode_systemwide's LengthOfTimeExperiencingHomelessness field.
"""
import pandas as pd

from .config import DIMENSIONS, DIMENSION_COLUMNS, POPULATION_SEGMENTS
from .population import filter_population


def _all_categories(df: pd.DataFrame, dimension: str) -> list:
    """Every category value that appears anywhere in `df` for this
    dimension — every month/segment slice is reindexed against this full
    set so a category with zero people that slice still emits an explicit
    n=0 row instead of being silently absent (see _stats_by_category)."""
    if dimension == "overall":
        return ["Overall"]
    return sorted(df[DIMENSION_COLUMNS[dimension]].dropna().unique().tolist())


def _stats_by_category(df: pd.DataFrame, dimension: str, all_categories: list) -> list[dict]:
    length_col = "LengthOfTimeExperiencingHomelessness"
    if dimension == "overall":
        groups = {"Overall": df}
    else:
        category_col = DIMENSION_COLUMNS[dimension]
        groups = {name: g for name, g in df.groupby(category_col)}

    out = []
    # Iterate the full category set (not just groups.keys()) — a category
    # absent from this slice still needs an explicit n=0 row, otherwise a
    # lone suppressed cell has no sibling row for suppression.py's
    # secondary-suppression pass to additionally hide.
    for category in all_categories:
        group = groups.get(category)
        lengths = group[length_col].dropna() if group is not None else pd.Series(dtype=float)
        out.append(
            {
                "category": category,
                "n": len(lengths),
                "median_days": lengths.median() if len(lengths) else None,
                "p25_days": lengths.quantile(0.25) if len(lengths) else None,
                "p75_days": lengths.quantile(0.75) if len(lengths) else None,
                "mean_days": lengths.mean() if len(lengths) else None,
            }
        )
    return out


def build_length_rows(episodes: pd.DataFrame) -> pd.DataFrame:
    # EpisodeOutflowType is a per-*episode* label (an episode's eventual
    # final disposition, stamped on every monthly row it spans — see
    # Episode_Systemwide notebook's process_episode()), not a per-month
    # "still active this month" flag. Filtering rows to EpisodeOutflowType
    # == "Active" therefore keeps only people whose CURRENT episode is
    # still ongoing as of query time — for an old month, that's only the
    # small slice of people who have been continuously homeless ever
    # since, a severe survivorship-bias sample that inflates length-of-time
    # stats for older months and lets them fall toward the present as less
    # time has had a chance to introduce that bias. Use the same "active as
    # of this month's end" population as build_flow.py's active_total
    # instead: every row that isn't that same episode's own closing month.
    episodes = episodes.copy()
    start_period = episodes["EpisodeStartDate"].dt.to_period("M")
    end_period = episodes["EpisodeEndDate"].dt.to_period("M")
    time_period = episodes["TimePeriodStartDate"].dt.to_period("M")
    episodes["_is_outflow_row"] = (time_period == end_period) & (episodes["EpisodeOutflowType"] != "Active")

    rows: list = []
    months = sorted(episodes["TimePeriodStartDate"].unique())

    # See build_flow.py's identical pattern: derived once from the full
    # window, not per-slice, so every slice reindexes against a stable set.
    all_categories = {dimension: _all_categories(episodes, dimension) for dimension in DIMENSIONS}

    for month in months:
        month_df = episodes[episodes["TimePeriodStartDate"] == month]
        active_df = month_df[~month_df["_is_outflow_row"]]

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_df = filter_population(active_df, pop_label, month)

            for dimension in DIMENSIONS:
                for stat_row in _stats_by_category(pop_df, dimension, all_categories[dimension]):
                    rows.append(
                        {
                            "month": month,
                            "population_segment": segment_key,
                            "dimension": dimension,
                            **stat_row,
                        }
                    )

    df = pd.DataFrame(rows)
    # n < 11 drives suppression for this table (suppression.py operates on a
    # "count" column by convention; alias n -> count for the shared pipeline,
    # then alias back before export).
    df = df.rename(columns={"n": "count"})
    return df
