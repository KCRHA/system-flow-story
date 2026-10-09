"""Builds dashboard_length_by_exit_monthly and dashboard_length_headline_yearly:
distribution stats (median/p25/p75/mean) for how long people were actively
experiencing homelessness, split by how their time active ended — permanently
housed, inactive, aged out of YYA, or (headline table only) still active —
instead of build_length.py's single pooled "active population each month"
series, which silently mixed people still experiencing homelessness with
people who'd already exited.

Sourced from episode_systemwide's LengthOfTimeExperiencingHomelessness field,
same as build_length.py, read directly off the episode's own closing
(outflow) row for a real HUD exit (Permanently Housed/Inactive/Deceased) —
that row already carries the episode's total duration, confirmed alongside
EpisodeOutflowType on the very same row, no join needed.

"Aged out" has no real EpisodeOutflowType/outflow row of its own — it's a
population-membership dropout (YYA only; see population.py's filter_population
YYA branch), not an episode closure. Duration there is a date delta instead:
the aging-out cutoff date minus EpisodeStartDate. Detecting *who* aged out
within a given month mirrors build_flow.py's _partition_by_individual (its
own "Aged out" docstring section has the full rationale for the two signals
used) — duplicated here as _aged_out_cutoffs_for_month rather than imported,
since _partition_by_individual only returns id sets (no cutoff date) and is
deeply entangled with the inflow/outflow partition machinery the sankey/KPI
cards need; this module only needs the aged-out piece. If that detection
logic ever changes in build_flow.py, this copy needs the same change.
"""
import pandas as pd

from .config import DIMENSION_COLUMNS, OUTFLOW_TYPE_MAP, POPULATION_SEGMENTS, PROJECT_ENGAGEMENT_DIMENSIONS
from .period_dimensions import (
    _BINARY_CATEGORIES,
    EXTENDED_DIMENSIONS,
    PERIOD_AGGREGATE_CATEGORY_DIMENSIONS,
    _group_enrollments_by_dimension,
    _project_engagement_category,
    _unsheltered_in_period_category,
)
from .population import filter_population

_YYA_LABEL = "Youth and Young Adults"

# exit_type keys emitted by dashboard_length_by_exit_monthly — deceased is
# deliberately left out of this per-panel table (too small/suppressed to be
# worth its own chart; confirmed with the dashboard owner) even though the
# headline table below still pools it in, since the headline represents
# "everyone," not a per-status breakdown.
_PANEL_EXIT_TYPES = ["permanently_housed", "inactive", "aged_out"]


def _all_categories(df: pd.DataFrame, dimension: str) -> list:
    # unsheltered_in_period/project_engaged_* are fixed Included/Not
    # Included pairs, not data-derived — see build_length.py's identical
    # special-case for why (their DIMENSION_COLUMNS value doesn't exist yet
    # on `df` at the point this runs).
    if dimension == "overall":
        return ["Overall"]
    if dimension in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS:
        return _BINARY_CATEGORIES
    return sorted(df[DIMENSION_COLUMNS[dimension]].dropna().unique().tolist())


def _stats_by_category(df: pd.DataFrame, dimension: str, all_categories: list) -> list[dict]:
    if dimension == "overall":
        groups = {"Overall": df}
    else:
        category_col = DIMENSION_COLUMNS[dimension]
        groups = {name: g for name, g in df.groupby(category_col)}

    out = []
    for category in all_categories:
        group = groups.get(category)
        durations = group["_duration_days"].dropna() if group is not None else pd.Series(dtype=float)
        out.append(
            {
                "category": category,
                "n": len(durations),
                "median_days": durations.median() if len(durations) else None,
                "p25_days": durations.quantile(0.25) if len(durations) else None,
                "p75_days": durations.quantile(0.75) if len(durations) else None,
                "mean_days": durations.mean() if len(durations) else None,
            }
        )
    return out


def _dedupe_keep_longest_episode(df: pd.DataFrame) -> pd.DataFrame:
    """Collapses to one row per PersonalID, keeping the longest
    _duration_days — a person can have more than one episode close (or, for
    YYA, age out, or still be open) within the same displayed period (the
    minimum 30-day episode gap fits inside a single calendar month; two
    separate episodes can also both close within the same quarter/year), and
    counting each as its own data point would double-count that person in
    the median/percentile stats below."""
    return df.sort_values("_duration_days", ascending=False).drop_duplicates("PersonalID", keep="first")


def _flag_outflow_rows(episodes: pd.DataFrame) -> pd.DataFrame:
    episodes = episodes.copy()
    end_period = episodes["EpisodeEndDate"].dt.to_period("M")
    time_period = episodes["TimePeriodStartDate"].dt.to_period("M")
    episodes["_is_outflow_row"] = (time_period == end_period) & (episodes["EpisodeOutflowType"] != "Active")
    return episodes


def _real_exit_duration_df(episodes: pd.DataFrame) -> pd.DataFrame:
    """Every real HUD exit row (episodes must already carry _is_outflow_row
    — see _flag_outflow_rows), tagged with exit_type and _duration_days read
    straight off that same row. All three OUTFLOW_TYPE_MAP reasons included
    (permanently_housed/inactive/deceased) — callers that only want a subset
    (e.g. the by-exit panel table, which drops deceased) filter afterward."""
    exit_df = episodes[episodes["_is_outflow_row"]].copy()
    exit_df["exit_type"] = exit_df["EpisodeOutflowType"].map(OUTFLOW_TYPE_MAP)
    exit_df = exit_df[exit_df["exit_type"].notna()]
    exit_df["_duration_days"] = exit_df["LengthOfTimeExperiencingHomelessness"]
    return exit_df


def _aged_out_cutoffs_for_month(episodes: pd.DataFrame, month, prior_month) -> dict:
    """{PersonalID: cutoff_date} for everyone who aged out of YYA during
    `month` — an open episode that drops out of the YYA population filter
    this month with no real HUD outflow event of its own. Mirrors
    build_flow.py's _partition_by_individual aged-out detection (see this
    module's own top comment).

    cutoff_date is AgedOutOfYYA's own exact date when a confirming row
    exists this month (the primary signal); for the fallback signal (a
    still-open raw row this month that fails the YYA filter, with no
    confirming AgedOutOfYYA row inside this one month) `month` itself is
    used as a conservative approximation, since no more precise date is
    knowable from a single month in isolation.

    `episodes` must already carry _is_outflow_row (see _flag_outflow_rows).
    """
    month_df = episodes[episodes["TimePeriodStartDate"] == month]
    pop_df = filter_population(month_df, _YYA_LABEL, month)
    still_active_ids = set(pop_df.loc[~pop_df["_is_outflow_row"], "PersonalID"])

    if prior_month is not None:
        prior_df = episodes[episodes["TimePeriodStartDate"] == prior_month]
        prior_pop_df = filter_population(prior_df, _YYA_LABEL, prior_month)
        ever_active_ids = set(prior_pop_df.loc[~prior_pop_df["_is_outflow_row"], "PersonalID"])
    else:
        ever_active_ids = set()
    ever_active_ids |= still_active_ids

    aged_out_of_yya = pd.to_datetime(month_df["AgedOutOfYYA"], errors="coerce")
    exclusion_start_month = aged_out_of_yya.dt.to_period("M") + 1
    row_month = month_df["TimePeriodStartDate"].dt.to_period("M")
    is_aged_out_row = aged_out_of_yya.notna() & (row_month == exclusion_start_month)
    signal1 = month_df.loc[is_aged_out_row & month_df["PersonalID"].isin(ever_active_ids)]
    cutoff_by_id = dict(zip(signal1["PersonalID"], aged_out_of_yya.loc[signal1.index]))

    raw_open_ids = set(month_df.loc[~month_df["_is_outflow_row"], "PersonalID"])
    signal2_ids = (ever_active_ids & raw_open_ids) - still_active_ids
    for pid in signal2_ids:
        cutoff_by_id.setdefault(pid, pd.Timestamp(month))

    return {pid: cutoff for pid, cutoff in cutoff_by_id.items() if pid not in still_active_ids}


def _aged_out_events_df(episodes: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """One row per (PersonalID, month-they-aged-out), for every published
    month (window_start onward — see build_length_by_exit_rows/
    build_length_headline_rows' own window_start contract, mirroring
    build_flow_rows'), with exit_type="aged_out", _duration_days (cutoff
    date minus EpisodeStartDate), _cutoff_date (for bucketing into the
    headline table's calendar year), and every DIMENSION_COLUMNS value
    (read off that person's own row in the month they aged out, same as any
    other exit event). Empty for every population other than YYA by
    construction (_aged_out_cutoffs_for_month only ever returns non-empty
    for the YYA label). `episodes` may carry one extra lookback month before
    window_start (not itself emitted) so the window's own first published
    month can still resolve a true prior_month instead of treating everyone
    aged-out that month as having no prior history."""
    months = sorted(episodes["TimePeriodStartDate"].unique())
    month_index = {m: i for i, m in enumerate(months)}
    published_months = [m for m in months if window_start is None or m >= window_start]

    parts = []
    for month in published_months:
        prior_month = months[month_index[month] - 1] if month_index[month] > 0 else None
        cutoffs = _aged_out_cutoffs_for_month(episodes, month, prior_month)
        if not cutoffs:
            continue
        month_df = episodes[episodes["TimePeriodStartDate"] == month]
        aged_out_rows = month_df[month_df["PersonalID"].isin(cutoffs)].copy()
        # One row per PersonalID per month in episode_systemwide (see
        # build_flow.py's own comment on this invariant) — drop_duplicates
        # defensively in case of the rare same-month episode transition.
        aged_out_rows = aged_out_rows.drop_duplicates("PersonalID")
        aged_out_rows["exit_type"] = "aged_out"
        aged_out_rows["_cutoff_date"] = aged_out_rows["PersonalID"].map(cutoffs)
        aged_out_rows["_duration_days"] = (aged_out_rows["_cutoff_date"] - aged_out_rows["EpisodeStartDate"]).dt.days
        parts.append(aged_out_rows)

    if not parts:
        return episodes.iloc[0:0].assign(exit_type=pd.Series(dtype=object), _cutoff_date=pd.Series(dtype="datetime64[ns]"), _duration_days=pd.Series(dtype=float))
    return pd.concat(parts, ignore_index=True)


def build_length_by_exit_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """dashboard_length_by_exit_monthly: one row per (month,
    population_segment, dimension, category, exit_type), exit_type in
    permanently_housed/inactive/aged_out (see _PANEL_EXIT_TYPES).

    `episodes` may carry one extra lookback month before `window_start` (see
    export.py's episodes_with_lookback) — window_start, if given, restricts
    which months actually get emitted, while still letting the window's own
    first published month resolve a true prior_month for aged-out detection
    instead of treating everyone who ages out that month as having no prior
    history (same contract as build_flow.py's build_flow_rows).

    `enrollments`: raw All_Program_Enrollments rows, used only to resolve
    the project_engaged_* dimensions (see _project_engagement_category)."""
    episodes = _flag_outflow_rows(episodes)
    exit_df = _real_exit_duration_df(episodes)
    exit_df = exit_df[exit_df["exit_type"].isin(["permanently_housed", "inactive"])]
    aged_out_df = _aged_out_events_df(episodes, window_start=window_start)

    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    months = [m for m in all_months if window_start is None or m >= window_start]
    published = episodes[episodes["TimePeriodStartDate"].isin(months)]
    all_categories = {dimension: _all_categories(published, dimension) for dimension in EXTENDED_DIMENSIONS}
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for month in months:
        month_exit = exit_df[exit_df["TimePeriodStartDate"] == month]
        month_aged_out = aged_out_df[aged_out_df["TimePeriodStartDate"] == month] if not aged_out_df.empty else aged_out_df

        # unsheltered_in_period/project_engaged_* resolved fresh per month
        # from every one of that month's own episode rows (unfiltered by
        # exit/aged-out status or population) — same contract as
        # build_length.py's identical per-month resolution — then mapped
        # onto this month's exit/aged-out rows before they're combined.
        month_full_df = episodes[episodes["TimePeriodStartDate"] == month]
        period_start = pd.Timestamp(month)
        period_end = period_start + pd.offsets.MonthEnd(0)
        period_category = {
            "unsheltered_in_period": _unsheltered_in_period_category(month_full_df),
            **{
                dim: _project_engagement_category(month_full_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }
        month_exit = month_exit.assign(
            **{DIMENSION_COLUMNS[dim]: month_exit["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
        )
        month_aged_out = month_aged_out.assign(
            **{DIMENSION_COLUMNS[dim]: month_aged_out["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
        )

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_exit = filter_population(month_exit, pop_label, month)
            # Aged-out people have, by construction, just dropped OUT of the
            # YYA population filter this month — running them back through
            # filter_population would incorrectly exclude them. Added
            # directly instead, and only for the yya segment itself.
            pop_aged_out = month_aged_out if pop_label == _YYA_LABEL else month_aged_out.iloc[0:0]
            combined = pd.concat([pop_exit, pop_aged_out], ignore_index=True)
            # Collapsed BEFORE the exit_type split below: a person whose two
            # episodes closed with DIFFERENT exit types in the same month
            # (rare, but possible) should land in exactly one panel —
            # whichever episode was longest — not get counted once in each.
            combined = _dedupe_keep_longest_episode(combined)

            for dimension in EXTENDED_DIMENSIONS:
                categories = all_categories[dimension]
                for exit_type in _PANEL_EXIT_TYPES:
                    sub = combined[combined["exit_type"] == exit_type]
                    for stat_row in _stats_by_category(sub, dimension, categories):
                        rows.append(
                            {
                                "month": month,
                                "population_segment": segment_key,
                                "dimension": dimension,
                                "exit_type": exit_type,
                                **stat_row,
                            }
                        )

    df = pd.DataFrame(rows)
    df = df.rename(columns={"n": "count"})
    return df


def build_length_headline_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """dashboard_length_headline_yearly: one row per (year, population_segment,
    dimension, category) — a single pooled median/p25/p75 of days active,
    counting everyone active at any point that year: every real exit's
    duration (housed/inactive/deceased) for exits that fell in that year,
    aged-out people's computed duration (YYA only), and everyone still
    active as of the year's last available month, using their current-
    episode duration-so-far. Deliberately includes deceased (unlike
    dashboard_length_by_exit_monthly's own panel breakdown) since this is
    meant to represent "everyone," not a per-status chart.

    `episodes` may carry one extra lookback month before `window_start` —
    same contract as build_length_by_exit_rows above. get_export_window's
    start always falls on January 1st, so that lookback month is always
    December of the year before the first published year and can never
    itself land inside a published year's own pooled events.

    `enrollments`: raw All_Program_Enrollments rows, used only to resolve
    the project_engaged_* dimensions (see _project_engagement_category).
    """
    episodes = _flag_outflow_rows(episodes)
    exit_df = _real_exit_duration_df(episodes)
    aged_out_df = _aged_out_events_df(episodes, window_start=window_start)
    if not aged_out_df.empty:
        aged_out_df = aged_out_df.assign(_year=aged_out_df["_cutoff_date"].dt.year)

    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    months = [m for m in all_months if window_start is None or m >= window_start]
    years = sorted({pd.Timestamp(m).year for m in months})
    last_month_of_year = {}
    for m in months:
        y = pd.Timestamp(m).year
        if y not in last_month_of_year or m > last_month_of_year[y]:
            last_month_of_year[y] = m

    published = episodes[episodes["TimePeriodStartDate"].isin(months)]
    all_categories = {dimension: _all_categories(published, dimension) for dimension in EXTENDED_DIMENSIONS}
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for year in years:
        year_end_month = last_month_of_year[year]
        year_end_month_df = episodes[episodes["TimePeriodStartDate"] == year_end_month]
        year_end_active = year_end_month_df[~year_end_month_df["_is_outflow_row"]].copy()
        year_end_active["_duration_days"] = year_end_active["LengthOfTimeExperiencingHomelessness"]

        year_exit = exit_df[exit_df["TimePeriodStartDate"].apply(lambda m: pd.Timestamp(m).year) == year]
        year_aged_out = aged_out_df[aged_out_df["_year"] == year] if not aged_out_df.empty else aged_out_df

        # unsheltered_in_period/project_engaged_* resolved as an OR across
        # the WHOLE year's own episode rows (unfiltered by exit/active/
        # population status) — same "whichever period is being built"
        # contract as build_flow.py's build_flow_yearly_rows, just a year
        # here instead of a month.
        year_full_df = published[published["TimePeriodStartDate"].apply(lambda m: pd.Timestamp(m).year) == year]
        year_months = sorted(year_full_df["TimePeriodStartDate"].unique())
        period_start = pd.Timestamp(year_months[0])
        period_end = pd.Timestamp(year_months[-1]) + pd.offsets.MonthEnd(0)
        period_category = {
            "unsheltered_in_period": _unsheltered_in_period_category(year_full_df),
            **{
                dim: _project_engagement_category(year_full_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_active = filter_population(year_end_active, pop_label, year_end_month)

            # Each exit's own month determines the right filter_population
            # snapshot (YYA membership, chronic status, etc. are all
            # month-dependent) — exits within the same year can span many
            # different months, so this can't be filtered once against the
            # year as a whole.
            exit_parts = [
                filter_population(month_group, pop_label, month)
                for month, month_group in year_exit.groupby("TimePeriodStartDate")
            ]
            pop_exit = pd.concat(exit_parts, ignore_index=True) if exit_parts else year_exit.iloc[0:0]

            pop_aged_out = year_aged_out if pop_label == _YYA_LABEL else year_aged_out.iloc[0:0]

            combined = pd.concat([pop_active, pop_exit, pop_aged_out], ignore_index=True)
            # A person can have more than one episode touch the same year
            # (still-active + an earlier real exit, or two separate exits) —
            # collapse to their single longest episode before computing
            # stats, same reasoning as _dedupe_keep_longest_episode's own
            # docstring.
            combined = _dedupe_keep_longest_episode(combined)
            combined = combined.assign(
                **{DIMENSION_COLUMNS[dim]: combined["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
            )

            for dimension in EXTENDED_DIMENSIONS:
                categories = all_categories[dimension]
                for stat_row in _stats_by_category(combined, dimension, categories):
                    rows.append(
                        {
                            "year": year,
                            "population_segment": segment_key,
                            "dimension": dimension,
                            **stat_row,
                        }
                    )

    df = pd.DataFrame(rows)
    df = df.rename(columns={"n": "count"})
    return df


def build_length_headline_monthly_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """Builds dashboard_length_headline_monthly: one row per (month,
    population_segment, dimension, category) — the same pooled definition
    as build_length_headline_rows' yearly table (everyone active at any
    point in the period, counted as of their exit date if they left the
    system — Permanently Housed/Inactive/Deceased/Aged Out — or as of the
    period's end if they're still active), just at calendar-month grain
    instead of calendar year. Powers LengthSection's headline KPI card
    whenever a reader drills into a specific month rather than browsing a
    full year.

    `episodes` may carry one extra lookback month before `window_start` —
    same contract as build_length_by_exit_rows/build_length_headline_rows
    above (aged-out detection needs a true prior_month for the window's own
    first published month).

    `enrollments`: raw All_Program_Enrollments rows, used only to resolve
    the project_engaged_* dimensions (see _project_engagement_category).
    """
    episodes = _flag_outflow_rows(episodes)
    exit_df = _real_exit_duration_df(episodes)
    aged_out_df = _aged_out_events_df(episodes, window_start=window_start)

    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    months = [m for m in all_months if window_start is None or m >= window_start]
    published = episodes[episodes["TimePeriodStartDate"].isin(months)]
    all_categories = {dimension: _all_categories(published, dimension) for dimension in EXTENDED_DIMENSIONS}
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for month in months:
        month_full_df = episodes[episodes["TimePeriodStartDate"] == month]
        # This month's own "still active" snapshot — same ~_is_outflow_row
        # population build_length.py's active_df uses, resolved fresh here
        # since this builder doesn't share that module's dataframe.
        month_active = month_full_df[~month_full_df["_is_outflow_row"]].copy()
        month_active["_duration_days"] = month_active["LengthOfTimeExperiencingHomelessness"]

        month_exit = exit_df[exit_df["TimePeriodStartDate"] == month]
        month_aged_out = aged_out_df[aged_out_df["TimePeriodStartDate"] == month] if not aged_out_df.empty else aged_out_df

        period_start = pd.Timestamp(month)
        period_end = period_start + pd.offsets.MonthEnd(0)
        period_category = {
            "unsheltered_in_period": _unsheltered_in_period_category(month_full_df),
            **{
                dim: _project_engagement_category(month_full_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_active = filter_population(month_active, pop_label, month)
            pop_exit = filter_population(month_exit, pop_label, month)
            pop_aged_out = month_aged_out if pop_label == _YYA_LABEL else month_aged_out.iloc[0:0]

            combined = pd.concat([pop_active, pop_exit, pop_aged_out], ignore_index=True)
            # Same longest-episode collapse as the yearly headline builder —
            # a person can have both a still-open episode and a separate,
            # already-closed one within the same month.
            combined = _dedupe_keep_longest_episode(combined)
            combined = combined.assign(
                **{DIMENSION_COLUMNS[dim]: combined["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
            )

            for dimension in EXTENDED_DIMENSIONS:
                categories = all_categories[dimension]
                for stat_row in _stats_by_category(combined, dimension, categories):
                    rows.append(
                        {
                            "month": month,
                            "population_segment": segment_key,
                            "dimension": dimension,
                            **stat_row,
                        }
                    )

    df = pd.DataFrame(rows)
    df = df.rename(columns={"n": "count"})
    return df


def build_length_headline_quarterly_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """Builds dashboard_length_headline_quarterly: one row per (quarter,
    population_segment, dimension, category) — same pooled definition as
    build_length_headline_monthly_rows above, grouped by calendar quarter
    instead. `quarter` is that quarter's start date (e.g. Q3 2026 ->
    2026-07-01), matching dashboard_flow_quarterly's own convention. A
    quarter whose 3 calendar months aren't ALL present in the completed-
    months window is skipped entirely, not emitted as a partial quarter —
    same convention as build_flow_quarterly_rows.

    `episodes`/`enrollments`: same contract as
    build_length_headline_monthly_rows above.
    """
    episodes = _flag_outflow_rows(episodes)
    episodes["_quarter"] = episodes["TimePeriodStartDate"].dt.to_period("Q").dt.start_time
    exit_df = _real_exit_duration_df(episodes)
    exit_df = exit_df.assign(_quarter=exit_df["TimePeriodStartDate"].dt.to_period("Q").dt.start_time)
    aged_out_df = _aged_out_events_df(episodes, window_start=window_start)
    if not aged_out_df.empty:
        aged_out_df = aged_out_df.assign(_quarter=aged_out_df["TimePeriodStartDate"].dt.to_period("Q").dt.start_time)

    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    months = [m for m in all_months if window_start is None or m >= window_start]
    published = episodes[episodes["TimePeriodStartDate"].isin(months)]
    all_categories = {dimension: _all_categories(published, dimension) for dimension in EXTENDED_DIMENSIONS}
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for quarter, quarter_df in published.groupby("_quarter"):
        quarter_months = sorted(quarter_df["TimePeriodStartDate"].unique())
        if len(quarter_months) < 3:
            continue
        # Quarter-end snapshot for the "still active" population — same
        # "last available month" convention build_length_headline_rows uses
        # for a year's own year-end snapshot.
        last_month = quarter_months[-1]
        last_month_df = episodes[episodes["TimePeriodStartDate"] == last_month]
        quarter_active = last_month_df[~last_month_df["_is_outflow_row"]].copy()
        quarter_active["_duration_days"] = quarter_active["LengthOfTimeExperiencingHomelessness"]

        quarter_exit = exit_df[exit_df["_quarter"] == quarter]
        quarter_aged_out = aged_out_df[aged_out_df["_quarter"] == quarter] if not aged_out_df.empty else aged_out_df

        period_start = pd.Timestamp(quarter_months[0])
        period_end = pd.Timestamp(quarter_months[-1]) + pd.offsets.MonthEnd(0)
        period_category = {
            "unsheltered_in_period": _unsheltered_in_period_category(quarter_df),
            **{
                dim: _project_engagement_category(quarter_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            pop_active = filter_population(quarter_active, pop_label, last_month)
            # Each exit's own month determines the right filter_population
            # snapshot (YYA membership, chronic status, etc. are all
            # month-dependent) — exits within the same quarter can span up
            # to 3 different months, same reasoning as the yearly builder's
            # own exit_parts.
            exit_parts = [
                filter_population(month_group, pop_label, month)
                for month, month_group in quarter_exit.groupby("TimePeriodStartDate")
            ]
            pop_exit = pd.concat(exit_parts, ignore_index=True) if exit_parts else quarter_exit.iloc[0:0]
            pop_aged_out = quarter_aged_out if pop_label == _YYA_LABEL else quarter_aged_out.iloc[0:0]

            combined = pd.concat([pop_active, pop_exit, pop_aged_out], ignore_index=True)
            combined = _dedupe_keep_longest_episode(combined)
            combined = combined.assign(
                **{DIMENSION_COLUMNS[dim]: combined["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
            )

            for dimension in EXTENDED_DIMENSIONS:
                categories = all_categories[dimension]
                for stat_row in _stats_by_category(combined, dimension, categories):
                    rows.append(
                        {
                            "quarter": quarter,
                            "population_segment": segment_key,
                            "dimension": dimension,
                            **stat_row,
                        }
                    )

    df = pd.DataFrame(rows)
    df = df.rename(columns={"n": "count"})
    return df
