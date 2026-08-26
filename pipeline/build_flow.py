"""Builds dashboard_flow_monthly: one row per (month, population_segment,
dimension, category, flow_type). Sourced from episode_systemwide (inflow,
outflow, active/status, CE) joined to episode_ce for CE dates, plus an
enrollment-level table for the resource-access flow types.
"""
import pandas as pd

from .config import (
    DIMENSIONS,
    DIMENSION_COLUMNS,
    INFLOW_TYPE_MAP,
    OUTFLOW_TYPE_MAP,
    POPULATION_SEGMENTS,
    RESOURCE_PROJECT_TYPE_GROUPS,
)
from .population import filter_population, filter_population_enrollment


def _all_categories(df: pd.DataFrame, dimension: str, category_col_map: dict) -> list:
    """Every category value that appears anywhere in `df` for this
    dimension — used to reindex per-month/per-segment counts so a category
    with zero people that slice still gets an explicit 0 row, rather than
    silently having no row at all (see _count_by_category)."""
    if dimension == "overall":
        return ["Overall"]
    return sorted(df[category_col_map[dimension]].dropna().unique().tolist())


def _count_by_category(df: pd.DataFrame, dimension: str, all_categories: list) -> dict:
    if dimension == "overall":
        return {"Overall": len(df)}
    category_col = DIMENSION_COLUMNS[dimension]
    # Reindexed against the full category set (not just what this slice
    # happens to contain) — a category with zero matches here must still
    # emit an explicit 0 row. Without that, a group where every category
    # but one has zero people ends up with only the suppressed row and
    # nothing else, leaving suppression with no sibling row to additionally
    # hide alongside it (see suppression.py's secondary-suppression pass).
    return df.groupby(category_col).size().reindex(all_categories, fill_value=0).to_dict()


def _emit(rows: list, month, segment_key: str, dimension: str, flow_type: str, counts: dict):
    for category, count in counts.items():
        rows.append(
            {
                "month": month,
                "population_segment": segment_key,
                "dimension": dimension,
                "category": category,
                "flow_type": flow_type,
                "count": count,
            }
        )


def build_flow_rows(episodes: pd.DataFrame, episode_ce: pd.DataFrame) -> pd.DataFrame:
    """episodes: episode_systemwide rows scoped to the export window, with
    RaceAndEthnicity/Gender already joined in from Client_Demographics.

    episode_systemwide's own EpisodeInflowType/EpisodeOutflowType are
    computed once per *episode* (see Episode_Systemwide notebook's
    process_episode()) and stamped onto every monthly row that episode
    spans — they describe how the episode began/ended overall, not "did
    this person enter/exit the system in this specific month." Using them
    directly as monthly flow events (the original approach here) hugely
    overcounts inflow (an episode's origin label repeats every month it's
    active) and misattributes outflow to months before the person actually
    left, which also made active_total undercount anyone whose episode had
    since closed by query time — breaking the active(M) = active(M-1) +
    inflow(M) - outflow(M) identity a stock/flow model should satisfy.
    Instead, treat only an episode's *first* row (TimePeriodStartDate in
    the same month as EpisodeStartDate) as its inflow event, and only its
    *last* row (TimePeriodStartDate in the same month as EpisodeEndDate,
    when the episode has actually closed) as its outflow event.
    active_total(M) is then "active as of M's end" — every row in month M
    except the ones that are that same month's outflow event — which makes
    the conservation identity hold exactly by construction.
    """
    episodes = episodes.copy()
    start_period = episodes["EpisodeStartDate"].dt.to_period("M")
    end_period = episodes["EpisodeEndDate"].dt.to_period("M")
    time_period = episodes["TimePeriodStartDate"].dt.to_period("M")
    episodes["_is_inflow_row"] = time_period == start_period
    episodes["_is_outflow_row"] = (time_period == end_period) & (episodes["EpisodeOutflowType"] != "Active")

    rows: list = []
    months = sorted(episodes["TimePeriodStartDate"].unique())

    # Computed once across the full window (not per-slice) so every category
    # gets a consistent, stable set of options across every month and
    # population segment — and so a category with zero people in a given
    # slice still reindexes to an explicit 0 row (see _count_by_category).
    all_categories = {
        dimension: _all_categories(episodes, dimension, DIMENSION_COLUMNS) for dimension in DIMENSIONS
    }

    for month in months:
        month_df = episodes[episodes["TimePeriodStartDate"] == month]
        ce_active_ids = set(
            episode_ce.loc[
                (episode_ce["CEEntryDate"] <= month)
                & (episode_ce["CEExitDate"].isna() | (episode_ce["CEExitDate"] > month)),
                "PersonalID",
            ]
        )

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_df = filter_population(month_df, pop_label, month)
            inflow_df = pop_df[pop_df["_is_inflow_row"]]
            outflow_df = pop_df[pop_df["_is_outflow_row"]]
            active_df = pop_df[~pop_df["_is_outflow_row"]]

            for dimension in DIMENSIONS:
                categories = all_categories[dimension]
                for hud_value, flow_type in INFLOW_TYPE_MAP.items():
                    matched = inflow_df[inflow_df["EpisodeInflowType"] == hud_value]
                    _emit(rows, month, segment_key, dimension, flow_type, _count_by_category(matched, dimension, categories))

                for hud_value, flow_type in OUTFLOW_TYPE_MAP.items():
                    matched = outflow_df[outflow_df["EpisodeOutflowType"] == hud_value]
                    _emit(rows, month, segment_key, dimension, flow_type, _count_by_category(matched, dimension, categories))

                _emit(rows, month, segment_key, dimension, "active_total", _count_by_category(active_df, dimension, categories))

                for status, flow_type in [
                    ("Unsheltered", "unsheltered"),
                    ("Sheltered", "sheltered"),
                    ("Temporarily Housed", "temporarily_housed"),
                ]:
                    matched = active_df[active_df["LastShelterStatusInTimeframe"] == status]
                    _emit(rows, month, segment_key, dimension, flow_type, _count_by_category(matched, dimension, categories))

                ce_engaged = active_df[active_df["PersonalID"].isin(ce_active_ids)]
                ce_not_engaged = active_df[~active_df["PersonalID"].isin(ce_active_ids)]
                _emit(rows, month, segment_key, dimension, "active_ce_engaged", _count_by_category(ce_engaged, dimension, categories))
                _emit(rows, month, segment_key, dimension, "active_not_ce_engaged", _count_by_category(ce_not_engaged, dimension, categories))

    return pd.DataFrame(rows)


def _resource_type_bucket(hud_code) -> str | None:
    for bucket, codes in RESOURCE_PROJECT_TYPE_GROUPS.items():
        if hud_code in codes:
            return bucket
    return None


def _count_by_category_enrollment(df: pd.DataFrame, dimension: str, all_categories: list) -> dict:
    from .config import ENROLLMENT_DIMENSION_COLUMNS

    if dimension == "overall":
        return {"Overall": df["PersonalID"].nunique()}
    category_col = ENROLLMENT_DIMENSION_COLUMNS[dimension]
    # Same reindex-against-the-full-set fix as _count_by_category, applied
    # to the enrollment-level (nunique PersonalID) count used by resource_*.
    return df.groupby(category_col)["PersonalID"].nunique().reindex(all_categories, fill_value=0).to_dict()


def build_resource_access_rows(enrollments: pd.DataFrame, client_demographics: pd.DataFrame, months: list) -> pd.DataFrame:
    """Resource-access flow types (resource_{type}_engaged/newly_enrolled/exited)
    are enrollment-level, not episode-level, so they're sourced from
    All_Program_Enrollments (one row per enrollment, spanning
    ProjectStartDate..ProjectExitDate) rather than episode_systemwide —
    confirmed directly against All_Program_Enrollments_2026_01_22.ipynb's
    final columns_to_select, joined to Client_Demographics on PersonalID for
    RaceAndEthnicity/Gender/VeteranStatus (none of which are native to the
    enrollment table itself).

    `enrollments` is expected raw (one row per enrollment span, no
    TimePeriodStartDate column — this table has no monthly grain of its own,
    unlike episode_systemwide, so the monthly panel is built here from
    ProjectStartDate/ProjectExitDate against the `months` list).
    """
    enrollments = enrollments.merge(
        client_demographics[["PersonalID", "RaceAndEthnicity", "Gender", "VeteranStatus"]],
        on="PersonalID",
        how="left",
    )
    enrollments["_bucket"] = enrollments["ProjectTypeCode"].apply(_resource_type_bucket)
    enrollments = enrollments.dropna(subset=["_bucket"])

    from .config import ENROLLMENT_DIMENSION_COLUMNS

    # Same rationale as build_flow_rows: derive the full category set once,
    # from the whole (bucketed) enrollment table, so every slice reindexes
    # against a stable set and zero-count categories get an explicit 0 row.
    all_categories = {
        dimension: _all_categories(enrollments, dimension, ENROLLMENT_DIMENSION_COLUMNS) for dimension in DIMENSIONS
    }

    rows: list = []
    for month in months:
        month_start = pd.Timestamp(month)
        month_end = month_start + pd.offsets.MonthEnd(0)

        engaged_mask = (enrollments["ProjectStartDate"] <= month_end) & (
            enrollments["ProjectExitDate"].isna() | (enrollments["ProjectExitDate"] >= month_start)
        )
        month_df = enrollments[engaged_mask]
        newly_enrolled_mask = enrollments["ProjectStartDate"].between(month_start, month_end)
        exited_mask = enrollments["ProjectExitDate"].between(month_start, month_end)

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_engaged = filter_population_enrollment(month_df, pop_label)
            pop_newly_enrolled = filter_population_enrollment(enrollments[newly_enrolled_mask], pop_label)
            pop_exited = filter_population_enrollment(enrollments[exited_mask], pop_label)

            for dimension in DIMENSIONS:
                categories = all_categories[dimension]
                for bucket in RESOURCE_PROJECT_TYPE_GROUPS:
                    engaged = pop_engaged[pop_engaged["_bucket"] == bucket]
                    newly_enrolled = pop_newly_enrolled[pop_newly_enrolled["_bucket"] == bucket]
                    exited = pop_exited[pop_exited["_bucket"] == bucket]
                    _emit(rows, month, segment_key, dimension, f"resource_{bucket}_engaged", _count_by_category_enrollment(engaged, dimension, categories))
                    _emit(rows, month, segment_key, dimension, f"resource_{bucket}_newly_enrolled", _count_by_category_enrollment(newly_enrolled, dimension, categories))
                    _emit(rows, month, segment_key, dimension, f"resource_{bucket}_exited", _count_by_category_enrollment(exited, dimension, categories))

    return pd.DataFrame(rows)
