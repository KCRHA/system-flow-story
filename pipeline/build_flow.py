"""Builds dashboard_flow_monthly: one row per (month, population_segment,
dimension, category, flow_type). Sourced from episode_systemwide (inflow,
outflow, active/status, CE) joined to episode_ce for CE dates, plus an
enrollment-level table for the resource-access flow types.
"""
import numpy as np
import pandas as pd

from .config import (
    DIMENSIONS,
    DIMENSION_COLUMNS,
    INFLOW_TYPE_MAP,
    OUTFLOW_TYPE_MAP,
    POPULATION_SEGMENTS,
    PROJECT_ENGAGEMENT_DIMENSIONS,
    PROJECT_ENGAGEMENT_GROUPS,
    RACE_DIMENSIONS,
    RESOURCE_PROJECT_TYPE_GROUPS,
)

# The 8 derived race_* columns (see demographics.py's compute_race_rollups) —
# same rationale as export.py's identical constant: sourced from
# DIMENSION_COLUMNS so it can't drift out of sync with config.py.
_RACE_ROLLUP_COLUMNS = [DIMENSION_COLUMNS[d] for d in RACE_DIMENSIONS]
from .population import filter_population, filter_population_enrollment

# dashboard_flow_monthly/yearly/quarterly's own dimension list, layered on
# top of config.DIMENSIONS with "unsheltered_in_period" and the
# project_engaged_* dimensions — see config.py's own comments on DIMENSIONS/
# PROJECT_ENGAGEMENT_GROUPS for why these can't live in the list every other
# build_*.py module shares. Only the three build_flow_*_rows functions below
# use this; build_resource_access_rows deliberately keeps using plain
# DIMENSIONS (it already has its own, differently-grouped project-type
# breakdown — RESOURCE_PROJECT_TYPE_GROUPS — and doesn't need this one too).
FLOW_DIMENSIONS = [*DIMENSIONS, "unsheltered_in_period", *PROJECT_ENGAGEMENT_DIMENSIONS]

_BINARY_CATEGORIES = ["Included", "Not Included"]


def _all_categories(df: pd.DataFrame, dimension: str, category_col_map: dict) -> list:
    """Every category value that appears anywhere in `df` for this
    dimension — used to reindex per-month/per-segment counts so a category
    with zero people that slice still gets an explicit 0 row, rather than
    silently having no row at all (see _count_by_category)."""
    if dimension == "overall":
        return ["Overall"]
    if dimension in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS:
        # Fixed Included/Not Included pair, same convention as the race_*
        # dimensions — not data-derived like every other branch here, since
        # none of these dimensions' columns exist yet on `df` at the point
        # this runs (each is computed fresh per period — see
        # _unsheltered_in_period_category/_project_engagement_category),
        # only once the per-period loop below actually builds them.
        return _BINARY_CATEGORIES
    return sorted(df[category_col_map[dimension]].dropna().unique().tolist())


def _count_by_category(df: pd.DataFrame, dimension: str, all_categories: list) -> dict:
    # nunique(PersonalID), not len()/.size(): episode_systemwide normally
    # carries at most one row per (PersonalID, month) — episodes for one
    # person are sequential and non-overlapping — but a person whose prior
    # episode closes and next episode opens within the same calendar month
    # (a real case: the minimum 30-day gap between episodes fits inside a
    # 31-day month) gets TWO rows that month, one per episode. active_df
    # (active_total and everything derived from it) never actually hits
    # this — the closing episode's row is excluded via ~_is_outflow_row,
    # confirmed empirically (max 1 row per person-month there) — but
    # unfiltered pop_df (experienced_homelessness) does, and would silently
    # double-count that person without this.
    if dimension == "overall":
        return {"Overall": df["PersonalID"].nunique()}
    category_col = DIMENSION_COLUMNS[dimension]
    # Reindexed against the full category set (not just what this slice
    # happens to contain) — a category with zero matches here must still
    # emit an explicit 0 row. Without that, a group where every category
    # but one has zero people ends up with only the suppressed row and
    # nothing else, leaving suppression with no sibling row to additionally
    # hide alongside it (see suppression.py's secondary-suppression pass).
    return df.groupby(category_col)["PersonalID"].nunique().reindex(all_categories, fill_value=0).to_dict()


def _emit(rows: list, month, segment_key: str, dimension: str, flow_type: str, counts: dict, extra: dict | None = None):
    for category, count in counts.items():
        row = {
            "month": month,
            "population_segment": segment_key,
            "dimension": dimension,
            "category": category,
            "flow_type": flow_type,
            "count": count,
        }
        if extra:
            row.update(extra)
        rows.append(row)


def _add_inflow_outflow_flags(episodes: pd.DataFrame) -> pd.DataFrame:
    """Adds _is_inflow_row/_is_outflow_row — see build_flow_rows's own
    docstring for why only an episode's first/last monthly row counts as
    its inflow/outflow event, not every row it spans. Factored out so
    build_flow_yearly_rows (and _partition_by_individual, called from
    both) can share it instead of recomputing it differently."""
    episodes = episodes.copy()
    start_period = episodes["EpisodeStartDate"].dt.to_period("M")
    end_period = episodes["EpisodeEndDate"].dt.to_period("M")
    time_period = episodes["TimePeriodStartDate"].dt.to_period("M")
    episodes["_is_inflow_row"] = time_period == start_period
    episodes["_is_outflow_row"] = (time_period == end_period) & (episodes["EpisodeOutflowType"] != "Active")
    return episodes


# Bucket keys _partition_by_individual returns, before the "indiv_" prefix
# flow_types get emitted under.
_ALREADY_ACTIVE = "already_active"
_STILL_ACTIVE = "still_active"
_AGED_OUT = "aged_out"

# Every inflow/outflow bucket key, in display order — already_active/
# still_active first, so a caller that wants them pinned to the top of
# the sankey's left/right columns can just preserve this order. aged_out
# sits right after still_active: like still_active, it's not one of
# episode_systemwide's own EpisodeOutflowType values (see OUTFLOW_TYPE_MAP)
# — it's specific to this partition's own bucketing, not a real HUD outflow
# reason.
INFLOW_BUCKET_KEYS = [_ALREADY_ACTIVE, *INFLOW_TYPE_MAP.values()]
OUTFLOW_BUCKET_KEYS = [_STILL_ACTIVE, _AGED_OUT, *OUTFLOW_TYPE_MAP.values()]


def _partition_by_individual(episodes: pd.DataFrame, pop_label: str, months: list, prior_month) -> dict:
    """For population `pop_label`, restricted to `months` (a list of
    consecutive TimePeriodStartDate values — one month for
    dashboard_flow_monthly, a whole calendar year's worth for
    dashboard_flow_yearly), classifies every distinct PersonalID who
    experienced homelessness during the period into exactly one inflow
    bucket and exactly one outflow bucket, AND pairs the two per person —
    e.g. "of the people newly homeless this period, how many were still
    active vs. permanently housed by period's end?" Unlike
    INFLOW_TYPE_MAP/OUTFLOW_TYPE_MAP's per-episode event counts (which the
    same person can contribute to more than once — e.g. newly homeless in
    February, returns from housed in October, or even a same-month
    episode transition, since the minimum 30-day episode gap fits inside
    a 31-day month), this is a true partition: the four inflow buckets
    sum to the same distinct-person total as the five outflow buckets,
    both equal to the period's experienced_homelessness count, and the
    20 (inflow, outflow) pairs sum to that same total again. Built for
    the sankey/KPI cards, which need to represent individuals, not
    episodes.

    Inflow priority: "already active" (an open episode as of the end of
    `prior_month`, checked against the RAW episode data — not whether that
    prior-month row itself passes filter_population, since YYA population
    membership is month-dependent and a person's episode can already be
    open before they become YYA-countable; see "Population membership can
    begin mid-episode" below) wins over any inflow event that also happens
    during the period — a person already homeless at the period's start
    who also opens a new episode partway through is still fundamentally
    "already active", not "newly arriving". Otherwise, their earliest
    inflow event within the period determines the bucket — also resolved
    against the raw episode data for the same reason, so a genuine inflow
    event isn't missed just because that one row happens to fail the
    population filter on its own.

    Outflow priority (symmetric): "still active" (active as of the end of
    the period's last month) wins over any earlier outflow event within
    the period — someone who exits and returns again before the period is
    over is, as of the period's end, still active. "Aged out" (YYA
    population only — see below) is checked next, then any earlier outflow
    event within the period. Otherwise, their latest outflow event within
    the period determines the bucket.

    Aged out: unlike every other population segment, filter_population's
    YYA branch is month-dependent — a person can drop out of the YYA
    segment mid-episode (their 25th birthday passes) with no inflow/
    outflow row involved at all. Two complementary signals catch this
    (confirmed against Episode_Systemwide's own source notebook — note
    EpisodeEndDate is NEVER actually null there: an episode still open as
    of the pipeline run gets EpisodeEndDate = that run's own date, not a
    missing value, so AgedOutOfYYA reliably gets backfilled even for
    still-open episodes once at least one full month has passed since the
    25th birthday):
      - AgedOutOfYYA, when present, is YBNL's own effective end date for
        this person's youth tracking, overriding EpisodeEndDate outright.
        The primary signal, and correct for the overwhelming majority of
        cases — but it only ever gets checked against rows WITHIN this
        function's own `months` window (via period_raw_df below), and a
        person whose 25th birthday falls in `months`' own LAST month has
        their confirming row (one month later) fall just outside that
        window, even though the row genuinely exists in the broader
        `episodes` table (the episode is still open well past this
        period). Confirmed via synthetic stress testing: ~0.03% of YYA
        period-members in a fully-completed past year hit this exact
        boundary gap.
      - The second signal below closes that gap directly, without relying
        on AgedOutOfYYA at all: anyone with a still-open raw row at
        `months`' own last month who nonetheless fails the population
        filter there (FlagYYA zeroed, whether from the 25th birthday or a
        later enrollment's own reassessment) is aged out just as surely,
        regardless of whether AgedOutOfYYA happens to have a matching row
        inside this specific window.
    Without an explicit bucket for this, such a person would silently
    disappear from every inflow/outflow bucket instead of landing in a
    dashboard-visible outflow reason, breaking the partition guarantee
    above.

    Population membership can begin mid-episode (YYA only): the mirror
    image of "aged out" above. Confirmed against Episode_Systemwide's own
    source notebook (DataHubDevelopment/Systemwide) — EpisodeAgeTier and
    FlagHeadOfHousehold are both fixed once per episode (age-at-start;
    "was anyone ever HoH at any point in the episode"), so neither one can
    flip mid-episode. FlagYYA is the one genuinely month-varying factor:
    it's `yya_status_asof`'s reading of whichever enrollment was open that
    month, and a single continuous episode can span multiple enrollments
    (e.g. moving between shelter programs while staying homeless) — an
    earlier enrollment can carry YYA=No (unset, or not yet reassessed)
    while a later one in the SAME episode correctly carries YYA=Yes, with
    no inflow/outflow event marking the transition. already_active_ids/
    inflow_candidates both resolve against the raw (not population-
    filtered) episode data for exactly this reason — see their own
    comments below.

    `episodes` must already carry _is_inflow_row/_is_outflow_row (see
    _add_inflow_outflow_flags) and span far enough back to include
    `prior_month`, which usually falls outside `months` itself (see
    build_flow_rows'/build_flow_yearly_rows' own window_start handling).
    """
    period_frames = [
        filter_population(episodes[episodes["TimePeriodStartDate"] == month], pop_label, month) for month in months
    ]
    period_pop_df = pd.concat(period_frames, ignore_index=True) if period_frames else episodes.iloc[0:0]
    period_ids = set(period_pop_df["PersonalID"])

    # Every raw (not population-filtered) row within the period — used
    # below for already_active_ids and inflow_candidates, not just the
    # YYA-only aged-out detection that originally lived here. See the
    # comments at each use for why: population membership for YYA is
    # month-dependent (filter_population's YYA branch — a person can
    # become HoH, or age from "Under 18" into "18 to 24", mid-episode),
    # so requiring a specific row to itself pass the population filter can
    # miss a real prior-active/inflow row that's population-eligible only
    # once you look across the row's own later history, not in isolation.
    period_raw_df = episodes[episodes["TimePeriodStartDate"].isin(months)]

    if prior_month is not None:
        prior_df = episodes[episodes["TimePeriodStartDate"] == prior_month]
        # Raw ~_is_outflow_row, not filter_population(prior_df, ...): a
        # person already homeless before the period started, who only
        # becomes YYA-countable partway through this period (see the
        # module docstring above), still had an open episode going into
        # the period — filtering prior_df by population here would miss
        # them entirely (they don't pass the filter at prior_month, only
        # later), leaving them with no inflow bucket at all even though
        # they're legitimately in period_ids. Scoped back to population
        # correctness by the `& period_ids` intersection below, which IS
        # the true population-filtered set for this period — this can
        # never let in someone who was never actually in-population at any
        # point in the period, just widens who counts as "already active"
        # among people who genuinely are.
        prior_active_ids = set(prior_df.loc[~prior_df["_is_outflow_row"], "PersonalID"])
    else:
        prior_active_ids = set()
    # Intersected with this period's own people defensively — every
    # already-active person should already have a row in the period's
    # first month (their episode must still be open to have been active
    # going into it), but the intersection costs nothing and guards
    # against that invariant ever drifting.
    already_active_ids = prior_active_ids & period_ids

    # The period's last month's pop_df is already sitting in
    # period_frames[-1] — reused rather than re-filtering.
    end_pop_df = period_frames[-1] if period_frames else episodes.iloc[0:0]
    still_active_ids = set(end_pop_df.loc[~end_pop_df["_is_outflow_row"], "PersonalID"])

    # Aged out of YYA (see this function's own docstring) — YYA population
    # only. YBNL's own end-date convention: AgedOutOfYYA, when present, IS
    # the effective end date for this person's youth tracking, taking
    # priority over EpisodeEndDate — independent of whether the underlying
    # HMIS episode has actually closed. `ever_active_ids` is deliberately
    # broader than prior_active_ids alone: a multi-month period (the
    # yearly builder) can see someone age out mid-period, well after the
    # period's own first month, so every month's own active-and-still-YYA
    # roster within the period is a candidate too, not just the one
    # carried in from prior_month.
    aged_out_ids: set = set()
    if pop_label == "Youth and Young Adults":
        # Seeded from the population-FILTERED prior-month roster, not raw
        # prior_active_ids: prior_active_ids is deliberately unfiltered (any
        # population, any age — see its own comment above) so that
        # already_active_ids can catch someone who only becomes YYA-countable
        # mid-period. Reusing that same raw set here would do the opposite of
        # what "ever_active_ids" is supposed to guard — instead of confirming
        # a person was genuinely YYA-eligible at some point in the period, it
        # would let in anyone merely active last month for ANY population
        # (e.g. a continuously-active 45-year-old single adult), who then
        # gets swept into aged_out_ids by the second signal below since they
        # fail today's YYA filter (they were never YYA to begin with). The
        # "becomes YYA mid-period" case doesn't need the raw seed anyway —
        # it's already caught by the period_frames union below, since
        # period_frames are population-filtered per month across the whole
        # `months` window.
        if prior_month is not None:
            prior_pop_df = filter_population(prior_df, pop_label, prior_month)
            ever_active_ids = set(prior_pop_df.loc[~prior_pop_df["_is_outflow_row"], "PersonalID"])
        else:
            ever_active_ids = set()
        for frame in period_frames:
            ever_active_ids |= set(frame.loc[~frame["_is_outflow_row"], "PersonalID"])

        # period_raw_df (not period_frames): someone who's just aged out has
        # already dropped out of the YYA-filtered population, so their row
        # only still exists in the raw episodes table.
        aged_out_of_yya = pd.to_datetime(period_raw_df["AgedOutOfYYA"], errors="coerce")
        # filter_population's own aged_out_before check (`< month_ts`) means
        # someone is still counted as active through the calendar month
        # AgedOutOfYYA itself falls in — exclusion only starts the following
        # month. Match THAT boundary (aged-out month + 1), not AgedOutOfYYA's
        # own month: matching its own month would never fire, since that
        # month they're still in still_active, not yet excluded.
        exclusion_start_month = aged_out_of_yya.dt.to_period("M") + 1
        row_month = period_raw_df["TimePeriodStartDate"].dt.to_period("M")
        is_aged_out_row = aged_out_of_yya.notna() & (row_month == exclusion_start_month)

        aged_out_ids = ever_active_ids & set(period_raw_df.loc[is_aged_out_row, "PersonalID"])

        # Second, complementary signal closing the months-window boundary
        # gap AgedOutOfYYA's exact-row match can miss (see this function's
        # own docstring's "Aged out" section): anyone with a raw, still-open
        # row (not _is_outflow_row) at the period's own LAST month, who
        # nonetheless fails the population filter there (not in
        # still_active_ids) — i.e. their episode is still literally going,
        # they've just turned 25 (or lost YYA eligibility some other way)
        # and FlagYYA was zeroed for it, whether or not the confirming
        # AgedOutOfYYA-matched row happens to fall inside this exact
        # `months` window. `ever_active_ids` confirms this is a genuine
        # aged-out transition (they WERE population-eligible earlier in
        # the period), not someone who was never YYA at any point in it.
        raw_end_df = period_raw_df[period_raw_df["TimePeriodStartDate"] == months[-1]]
        raw_end_open_ids = set(raw_end_df.loc[~raw_end_df["_is_outflow_row"], "PersonalID"])
        aged_out_ids |= (ever_active_ids & raw_end_open_ids) - still_active_ids

        # "Still active" wins over "aged out" per this function's own
        # documented outflow priority (see docstring) — without this, a
        # person whose AgedOutOfYYA falls inside the period but who is
        # ALSO still population-eligible and active as of the period's own
        # last month (e.g. a data quality case, or a person with more than
        # one concurrent episode) could land in both buckets at once,
        # double-counting them across outflow_buckets.
        aged_out_ids -= still_active_ids

    inflow_buckets = {_ALREADY_ACTIVE: already_active_ids}
    # period_raw_df, not period_pop_df: same reasoning as already_active_ids
    # above — a person's genuine inflow-type row (Newly Homeless/Return
    # from Housed/Return from Inactive) can itself fail the population
    # filter (their episode's earliest enrollment carried FlagYYA=No, not
    # yet reassessed) even though they later become a legitimate period
    # member via a later enrollment within the same episode. Restricted to
    # period_ids explicitly, since period_raw_df itself carries no
    # population filtering at all.
    inflow_candidates = period_raw_df[
        period_raw_df["_is_inflow_row"]
        & period_raw_df["EpisodeInflowType"].notna()
        & period_raw_df["PersonalID"].isin(period_ids)
        & ~period_raw_df["PersonalID"].isin(already_active_ids)
    ]
    earliest_inflow = (
        inflow_candidates.loc[inflow_candidates.groupby("PersonalID")["TimePeriodStartDate"].idxmin()]
        if not inflow_candidates.empty
        else inflow_candidates
    )
    for hud_value, key in INFLOW_TYPE_MAP.items():
        inflow_buckets[key] = set(earliest_inflow.loc[earliest_inflow["EpisodeInflowType"] == hud_value, "PersonalID"])

    outflow_buckets = {_STILL_ACTIVE: still_active_ids, _AGED_OUT: aged_out_ids}
    # period_raw_df, not period_pop_df: mirrors inflow_candidates above — a
    # person's genuine outflow-type row can itself fail the population
    # filter when their 25th birthday falls in the SAME month as their real
    # exit (FlagYYA is zeroed for that exact month, per Episode_Systemwide's
    # own AgedOutOfYYA/FlagYYA computation — see this function's docstring),
    # which would otherwise silently drop their real exit reason even though
    # neither still_active_ids nor aged_out_ids ends up catching them either
    # (their episode has, in fact, genuinely closed). Restricted to
    # period_ids explicitly, since period_raw_df carries no population
    # filtering at all.
    outflow_candidates = period_raw_df[
        period_raw_df["_is_outflow_row"]
        & period_raw_df["EpisodeOutflowType"].notna()
        & period_raw_df["PersonalID"].isin(period_ids)
        & ~period_raw_df["PersonalID"].isin(still_active_ids)
        & ~period_raw_df["PersonalID"].isin(aged_out_ids)
    ]
    latest_outflow = (
        outflow_candidates.loc[outflow_candidates.groupby("PersonalID")["TimePeriodStartDate"].idxmax()]
        if not outflow_candidates.empty
        else outflow_candidates
    )
    for hud_value, key in OUTFLOW_TYPE_MAP.items():
        outflow_buckets[key] = set(latest_outflow.loc[latest_outflow["EpisodeOutflowType"] == hud_value, "PersonalID"])

    # Per-person (inflow_bucket, outflow_bucket) pairing, then collapsed to
    # a count per pair — e.g. "how many of the people who were newly
    # homeless this period ended up permanently housed by period's end."
    # Every PersonalID in the period appears in exactly one bucket per
    # side (the two dicts above are each a true partition), so these two
    # Series share the same index set and align person-for-person.
    inflow_bucket_of = pd.concat(
        [pd.Series(key, index=list(ids)) for key, ids in inflow_buckets.items()]
    )
    outflow_bucket_of = pd.concat(
        [pd.Series(key, index=list(ids)) for key, ids in outflow_buckets.items()]
    )
    pairs = pd.DataFrame({"inflow_bucket": inflow_bucket_of, "outflow_bucket": outflow_bucket_of})
    full_pair_index = pd.MultiIndex.from_product([INFLOW_BUCKET_KEYS, OUTFLOW_BUCKET_KEYS])
    if not pairs.empty:
        pair_counts = pairs.groupby(["inflow_bucket", "outflow_bucket"]).size().reindex(full_pair_index, fill_value=0)
    else:
        pair_counts = pd.Series(0, index=full_pair_index)

    return {
        "inflow": inflow_buckets,
        "outflow": outflow_buckets,
        "pairs": {(a, b): int(n) for (a, b), n in pair_counts.items()},
        # Person-indexed, pre-collapse — kept alongside the already-collapsed
        # "pairs" counts above so a caller that wants a demographic
        # breakdown (see _partition_counts_by_category) can join a category
        # column onto it before grouping, instead of only ever seeing the
        # already-summed "overall" total.
        "pair_frame": pairs,
    }


# Dimensions _partition_counts_by_category can break indiv_*/indiv_flow_*
# out by category. FLOW_DIMENSIONS, not plain DIMENSIONS, so
# "unsheltered_in_period" gets this same indiv_* breakdown.
PARTITION_CATEGORY_DIMENSIONS = [d for d in FLOW_DIMENSIONS if d != "overall"]

# "household_type" and "age_category", unlike race_ethnicity/gender_identity/
# gender_alignment (client_demographics columns, genuinely constant for a
# person regardless of which episode they're in), are themselves
# episode-scoped: EpisodeHouseholdType/EpisodeAgeTier can differ between two
# of a person's own episodes (a household's composition can change; a
# person's age tier only increases, but can still cross tiers across a
# multi-year export window). A single person_category snapshot taken once
# across the WHOLE window — safe for every other PARTITION_CATEGORY_DIMENSIONS
# entry, since those really are constant — would misattribute anyone whose
# value actually changed to whichever value happened to survive
# drop_duplicates, regardless of which period is actually being built. See
# _person_category_for_period below, which build_flow_rows/
# build_flow_yearly_rows/build_flow_quarterly_rows use for these two
# instead, resolving each person's category fresh from just the period
# being built rather than a single global snapshot.
EPISODE_SCOPED_CATEGORY_DIMENSIONS = ["household_type", "age_category"]


def _person_category_for_period(period_df: pd.DataFrame, dimension: str) -> pd.Series:
    """PersonalID -> category, scoped to just `period_df` (this month's, or
    this year's/quarter's, own episode rows) — see
    EPISODE_SCOPED_CATEGORY_DIMENSIONS above for why these two dimensions
    can't reuse a single whole-window snapshot the way the others do.
    `period_df` must be unfiltered by population (not `pop_df`) so it still
    covers, e.g., someone who ages out of YYA and so drops out of the
    population-filtered rows for their last month in it (see
    _partition_by_individual's own aged-out handling) — every PersonalID
    that can end up in an inflow/outflow bucket or experienced_homelessness
    count for this period has at least one row here by construction (they
    can only reach those buckets via a row inside this same period, or via
    prior_month for already_active, which the caller folds in already since
    already_active_ids is intersected with period_ids first).

    Picks each person's LATEST row within the period when they have more
    than one (age only increases, so this is also the most current value;
    for household_type this is an arbitrary-but-consistent tiebreak, same
    as any other groupby-based pick elsewhere in this module)."""
    category_col = DIMENSION_COLUMNS[dimension]
    ordered = period_df.sort_values("TimePeriodStartDate")
    return ordered.drop_duplicates("PersonalID", keep="last").set_index("PersonalID")[category_col]


# "unsheltered_in_period" (and, for the same reason, every project_engaged_*
# dimension) needs a third resolution strategy, distinct from both
# EPISODE_SCOPED_CATEGORY_DIMENSIONS' "pick this period's latest row" and
# the plain whole-window snapshot: whether a person was EVER Unsheltered (or
# EVER enrolled in a matching project type) at any point in the period being
# built, an OR across every row/enrollment they have in it, not a single
# row's value — "did this person experience unsheltered homelessness" or
# "was this person engaged with Emergency Shelter" this month/quarter/year
# is itself an inherently period-level question, unlike age_category's or
# household_type's single current value. See _unsheltered_in_period_category
# and _project_engagement_category below.
PERIOD_AGGREGATE_CATEGORY_DIMENSIONS = ["unsheltered_in_period", *PROJECT_ENGAGEMENT_DIMENSIONS]


def _unsheltered_in_period_category(period_df: pd.DataFrame) -> pd.Series:
    """PersonalID -> "Included"/"Not Included", true if ANY of the person's
    rows within `period_df` (this month's, quarter's, or year's own episode
    rows — unfiltered by population, same contract as
    _person_category_for_period) has LastShelterStatusInTimeframe ==
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


# The subset of PARTITION_CATEGORY_DIMENSIONS that really is safe to
# snapshot once across the whole window (see EPISODE_SCOPED_CATEGORY_DIMENSIONS
# and PERIOD_AGGREGATE_CATEGORY_DIMENSIONS above for the ones that aren't).
_CONSTANT_CATEGORY_DIMENSIONS = [
    d for d in PARTITION_CATEGORY_DIMENSIONS if d not in EPISODE_SCOPED_CATEGORY_DIMENSIONS and d not in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS
]


def _partition_counts_by_category(partition: dict, cat_series: pd.Series, categories: list) -> tuple[dict, dict]:
    """Breaks one dimension's worth of indiv_*/indiv_flow_* counts out by
    category, given `cat_series` (that dimension's PersonalID -> category
    lookup) and `categories` (the dimension's full category set, for 0-fill
    reindexing — see _count_by_category's identical convention elsewhere).

    Returns (bucket_counts, pair_counts):
      bucket_counts: {bucket_key: {category: count}} — one entry per
        inflow_buckets/outflow_buckets key.
      pair_counts: {(inflow_key, outflow_key): {category: count}} — one
        entry per (inflow bucket, outflow bucket) combination.
    """
    bucket_counts = {}
    for key, ids in {**partition["inflow"], **partition["outflow"]}.items():
        counts = cat_series.reindex(list(ids)).value_counts()
        bucket_counts[key] = counts.reindex(categories, fill_value=0).astype(int).to_dict()

    pair_frame = partition["pair_frame"]
    pair_frame = pair_frame.assign(_category=cat_series.reindex(pair_frame.index))
    full_pair_category_index = pd.MultiIndex.from_product([INFLOW_BUCKET_KEYS, OUTFLOW_BUCKET_KEYS, categories])
    if not pair_frame.empty:
        grouped = pair_frame.groupby(["inflow_bucket", "outflow_bucket", "_category"]).size()
    else:
        grouped = pd.Series(dtype=int)
    grouped = grouped.reindex(full_pair_category_index, fill_value=0)

    pair_counts = {}
    for (inflow_key, outflow_key), sub in grouped.groupby(level=[0, 1]):
        pair_counts[(inflow_key, outflow_key)] = {cat: int(n) for (_, _, cat), n in sub.items()}

    return bucket_counts, pair_counts


def build_flow_rows(episodes: pd.DataFrame, episode_ce: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """episodes: episode_systemwide rows scoped to the export window, with
    the race_*/gender_* rollup columns already joined in from
    Client_Demographics. May additionally carry one lookback month before
    window_start (see export.py's episodes_with_lookback) — window_start,
    if given, restricts
    which months actually get emitted as rows, while still letting the
    window's own first published month resolve a true prior_month for
    _partition_by_individual's already-active/aged-out detection instead of
    treating everyone whose episode predates the window as brand new.

    enrollments: raw All_Program_Enrollments rows (one per enrollment span,
    ProjectTypeCode already mapped to numeric HUD codes, ProjectStartDate/
    ProjectExitDate already parsed) — not date-scoped to the export window
    at all, unlike `episodes`: a long-open enrollment that started years
    before the window must still count as overlapping this window's
    periods. Used only to resolve the project_engaged_* dimensions (see
    _project_engagement_category); has no bearing on any other flow_type.

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
    episodes = _add_inflow_outflow_flags(episodes)

    rows: list = []
    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    month_index = {m: i for i, m in enumerate(all_months)}
    months = [m for m in all_months if window_start is None or m >= window_start]

    # Computed once across the full published window (not per-slice, and
    # excluding any lookback month) so every category gets a consistent,
    # stable set of options across every month and population segment —
    # and so a category with zero people in a given slice still reindexes
    # to an explicit 0 row (see _count_by_category).
    published = episodes[episodes["TimePeriodStartDate"].isin(months)]
    all_categories = {
        dimension: _all_categories(published, dimension, DIMENSION_COLUMNS) for dimension in FLOW_DIMENSIONS
    }

    # PersonalID -> category, one lookup per demographic dimension (see
    # PARTITION_CATEGORY_DIMENSIONS) — used to break the indiv_*/indiv_flow_*
    # partition out by category below. Built once from the full episodes
    # frame (not per-month) since these columns are constant for a given
    # person regardless of which of their episodes/months it's read from.
    # EPISODE_SCOPED_CATEGORY_DIMENSIONS are deliberately left out of this
    # one-time snapshot — resolved fresh per month below instead (see
    # _person_category_for_period).
    person_category = {
        dimension: episodes.drop_duplicates("PersonalID").set_index("PersonalID")[DIMENSION_COLUMNS[dimension]]
        for dimension in _CONSTANT_CATEGORY_DIMENSIONS
    }
    # ProjectTypeCode-filtered once per project_engaged_* dimension, reused
    # across every month below — see _group_enrollments_by_dimension.
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    for month in months:
        prior_month = all_months[month_index[month] - 1] if month_index[month] > 0 else None
        month_df = episodes[episodes["TimePeriodStartDate"] == month]
        period_start = pd.Timestamp(month)
        period_end = period_start + pd.offsets.MonthEnd(0)
        # This month's own category lookup, constant dimensions plus this
        # month's freshly-resolved episode-scoped ones — see
        # EPISODE_SCOPED_CATEGORY_DIMENSIONS — and unsheltered_in_period's/
        # project_engaged_*'s own OR-across-the-month resolution (see
        # PERIOD_AGGREGATE_CATEGORY_DIMENSIONS).
        period_category = {
            **person_category,
            **{dim: _person_category_for_period(month_df, dim) for dim in EPISODE_SCOPED_CATEGORY_DIMENSIONS},
            "unsheltered_in_period": _unsheltered_in_period_category(month_df),
            **{
                dim: _project_engagement_category(month_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }
        # Broadcast this month's PERIOD_AGGREGATE_CATEGORY_DIMENSIONS
        # categories back onto every one of month_df's own rows (inflow/
        # outflow/active alike), so the per-flow-type/dimension loop below
        # — which groups the raw dataframe by DIMENSION_COLUMNS[dimension]
        # directly, unlike the indiv_*/period_category-driven partition
        # below it — can break any flow_type out by them the same way it
        # already does for every native column dimension.
        month_df = month_df.assign(
            **{DIMENSION_COLUMNS[dim]: month_df["PersonalID"].map(period_category[dim]) for dim in PERIOD_AGGREGATE_CATEGORY_DIMENSIONS}
        )
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

            for dimension in FLOW_DIMENSIONS:
                categories = all_categories[dimension]
                for hud_value, flow_type in INFLOW_TYPE_MAP.items():
                    matched = inflow_df[inflow_df["EpisodeInflowType"] == hud_value]
                    _emit(rows, month, segment_key, dimension, flow_type, _count_by_category(matched, dimension, categories))

                for hud_value, flow_type in OUTFLOW_TYPE_MAP.items():
                    matched = outflow_df[outflow_df["EpisodeOutflowType"] == hud_value]
                    _emit(rows, month, segment_key, dimension, flow_type, _count_by_category(matched, dimension, categories))

                _emit(rows, month, segment_key, dimension, "active_total", _count_by_category(active_df, dimension, categories))

                # Distinct people who touched the system this month at all
                # — active_total plus anyone whose episode also *closed*
                # this month (active_total alone excludes them via
                # ~_is_outflow_row, since it's specifically "active as of
                # month end"). Deliberately pop_df, not active_df: someone
                # who arrived and exited in the same month still
                # experienced homelessness that month. One row per person
                # per month in episode_systemwide (see the CUI-fan-out
                # dedup in export.py), so this is a true distinct-person
                # count, not an event count.
                _emit(rows, month, segment_key, dimension, "experienced_homelessness", _count_by_category(pop_df, dimension, categories))

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

            # Individual-level partition for the sankey/KPI cards (see
            # _partition_by_individual). Kept separate from the dimension
            # loop above: those flow_types (newly_homeless, active_total,
            # etc.) are deliberately still per-episode event counts,
            # matching standard flow reporting — these indiv_* ones are the
            # person-partitioned counterpart, not a replacement.
            partition = _partition_by_individual(episodes, pop_label, [month], prior_month)
            for key, ids in {**partition["inflow"], **partition["outflow"]}.items():
                _emit(rows, month, segment_key, "overall", f"indiv_{key}", {"Overall": len(ids)})

            # Per-person (inflow, outflow) pairing — lets the sankey trace,
            # e.g., where people who were newly homeless this period ended
            # up. inflow_bucket/outflow_bucket (on top of flow_type, which
            # already encodes both) give suppression.py's
            # apply_crosstab_secondary_suppression a clean, explicit way to
            # group "every cell sharing this inflow bucket" (a row) and
            # "every cell sharing this outflow bucket" (a column) without
            # parsing the flow_type string — each such group sums to a
            # separately-published total (indiv_newly_homeless etc.), so a
            # lone suppressed cell in either needs the same protection
            # dimension-category siblings already get elsewhere.
            for (inflow_key, outflow_key), count in partition["pairs"].items():
                _emit(
                    rows,
                    month,
                    segment_key,
                    "overall",
                    f"indiv_flow_{inflow_key}_to_{outflow_key}",
                    {"Overall": count},
                    extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                )

            # Same partition, broken out per demographic category (see
            # PARTITION_CATEGORY_DIMENSIONS/_partition_counts_by_category) —
            # lets the sankey/KPI cards scope to a demographic slice, same
            # as the dimension loop above already lets the rest of the
            # dashboard do.
            for dimension in PARTITION_CATEGORY_DIMENSIONS:
                categories = all_categories[dimension]
                bucket_counts, pair_counts = _partition_counts_by_category(partition, period_category[dimension], categories)
                for key, counts in bucket_counts.items():
                    _emit(rows, month, segment_key, dimension, f"indiv_{key}", counts)
                for (inflow_key, outflow_key), counts in pair_counts.items():
                    _emit(
                        rows,
                        month,
                        segment_key,
                        dimension,
                        f"indiv_flow_{inflow_key}_to_{outflow_key}",
                        counts,
                        extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                    )

    return pd.DataFrame(rows)


def build_flow_yearly_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """Builds dashboard_flow_yearly: one row per (year, population_segment,
    dimension, category, flow_type) — same shape as dashboard_flow_monthly
    (month -> year), carrying:

    enrollments: same contract as build_flow_rows' own `enrollments` param
    — raw, not window-scoped, used only to resolve project_engaged_*.

    window_start: same lookback contract as build_flow_rows — `episodes`
    may carry one extra month before window_start (see export.py's
    episodes_with_lookback), used only to resolve the earliest published
    year's prior_month. Grouping into years is restricted to window_start
    onward so that lookback month never becomes its own (partial,
    unpublished-elsewhere) year on its own.

    - experienced_homelessness: the count of *distinct* PersonalIDs with
      any row (active or exiting) at some point that calendar year. NOT
      the same as summing dashboard_flow_monthly's experienced_homelessness
      across a year's months: someone with more than one distinct episode
      in the same year (e.g. newly homeless in February, exits to
      housing, then returns from housed in October) would be counted in
      both months there, once per episode. This instead unions each
      month's matching PersonalIDs into one set per year before counting.

    - indiv_already_active/indiv_newly_homeless/indiv_return_from_housed/
      indiv_return_from_inactive/indiv_permanently_housed/indiv_inactive/
      indiv_deceased/indiv_still_active: the same true one-bucket-per-
      person partition as dashboard_flow_monthly's indiv_* flow_types,
      just over the whole year instead of one month — see
      _partition_by_individual.

    filter_population is applied per month (not once for the whole year)
    for the same reason every other build_*_rows caller does that — its
    YYA branch depends on each row's own month for the AgedOutOfYYA
    comparison; applying it once against the year's last month would
    misclassify anyone who aged out partway through.

    experienced_homelessness is always "overall"/"Overall" only (no
    breakdown) — still present so this fits the same shape
    apply_full_suppression_pipeline/validate expect, and so it's correctly
    treated as needing only primary suppression (no sibling categories in
    the group means no arithmetic recovery risk, same reasoning that
    already exempts every other table's own "overall" rows from secondary
    suppression). indiv_*/indiv_flow_* additionally get a per-category
    breakdown, same as dashboard_flow_monthly (see PARTITION_CATEGORY_DIMENSIONS).
    """
    episodes = _add_inflow_outflow_flags(episodes)
    episodes["_year"] = episodes["TimePeriodStartDate"].dt.year
    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    month_index = {m: i for i, m in enumerate(all_months)}
    published = episodes if window_start is None else episodes[episodes["TimePeriodStartDate"] >= window_start]

    # Same rationale as build_flow_rows's identical precompute — stable
    # across the whole window, not per-year, and these columns are constant
    # per person regardless of which year/episode they're read from.
    all_categories = {
        dimension: _all_categories(published, dimension, DIMENSION_COLUMNS) for dimension in FLOW_DIMENSIONS
    }
    # EPISODE_SCOPED_CATEGORY_DIMENSIONS deliberately left out of this
    # one-time snapshot — resolved fresh per year below instead (see
    # _person_category_for_period).
    person_category = {
        dimension: episodes.drop_duplicates("PersonalID").set_index("PersonalID")[DIMENSION_COLUMNS[dimension]]
        for dimension in _CONSTANT_CATEGORY_DIMENSIONS
    }
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for year, year_df in published.groupby("_year"):
        months = sorted(year_df["TimePeriodStartDate"].unique())
        prior_idx = month_index[months[0]] - 1
        prior_month = all_months[prior_idx] if prior_idx >= 0 else None
        period_start = pd.Timestamp(months[0])
        period_end = pd.Timestamp(months[-1]) + pd.offsets.MonthEnd(0)
        # This year's own category lookup — see EPISODE_SCOPED_CATEGORY_DIMENSIONS
        # and, for unsheltered_in_period/project_engaged_*, PERIOD_AGGREGATE_CATEGORY_DIMENSIONS.
        period_category = {
            **person_category,
            **{dim: _person_category_for_period(year_df, dim) for dim in EPISODE_SCOPED_CATEGORY_DIMENSIONS},
            "unsheltered_in_period": _unsheltered_in_period_category(year_df),
            **{
                dim: _project_engagement_category(year_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            person_ids: set = set()
            for month in months:
                month_df = year_df[year_df["TimePeriodStartDate"] == month]
                pop_df = filter_population(month_df, pop_label, month)
                person_ids.update(pop_df["PersonalID"])

            def _add(flow_type: str, count: int, dimension: str = "overall", category: str = "Overall", extra: dict | None = None):
                row = {
                    "year": int(year),
                    "population_segment": segment_key,
                    "dimension": dimension,
                    "category": category,
                    "flow_type": flow_type,
                    "count": count,
                }
                if extra:
                    row.update(extra)
                rows.append(row)

            _add("experienced_homelessness", len(person_ids))
            # Same per-category breakdown as indiv_*/indiv_flow_* below (see
            # PARTITION_CATEGORY_DIMENSIONS) — without this, buildFlowPeriod's
            # experiencedHomelessness lookup (sankeyData.js) always misses for
            # any non-overall dimension/category the frontend's demographic
            # filter selects, and a missing row silently resolves to 0 (not a
            # suppression marker) rather than surfacing as an error.
            for dimension in PARTITION_CATEGORY_DIMENSIONS:
                categories = all_categories[dimension]
                counts = (
                    period_category[dimension]
                    .reindex(list(person_ids))
                    .value_counts()
                    .reindex(categories, fill_value=0)
                    .astype(int)
                )
                for category, count in counts.items():
                    _add("experienced_homelessness", int(count), dimension=dimension, category=category)

            partition = _partition_by_individual(episodes, pop_label, months, prior_month)
            for key, ids in {**partition["inflow"], **partition["outflow"]}.items():
                _add(f"indiv_{key}", len(ids))
            # See build_flow_rows's own comment on indiv_flow_* /
            # inflow_bucket/outflow_bucket — same reasoning applies here.
            for (inflow_key, outflow_key), count in partition["pairs"].items():
                _add(
                    f"indiv_flow_{inflow_key}_to_{outflow_key}",
                    count,
                    extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                )

            # Same per-category breakdown as build_flow_rows — see its own
            # comment on why this lets the sankey/KPI cards scope to a
            # demographic slice.
            for dimension in PARTITION_CATEGORY_DIMENSIONS:
                categories = all_categories[dimension]
                bucket_counts, pair_counts = _partition_counts_by_category(partition, period_category[dimension], categories)
                for key, counts in bucket_counts.items():
                    for category, count in counts.items():
                        _add(f"indiv_{key}", count, dimension=dimension, category=category)
                for (inflow_key, outflow_key), counts in pair_counts.items():
                    for category, count in counts.items():
                        _add(
                            f"indiv_flow_{inflow_key}_to_{outflow_key}",
                            count,
                            dimension=dimension,
                            category=category,
                            extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                        )

    return pd.DataFrame(rows)


def build_flow_quarterly_rows(episodes: pd.DataFrame, enrollments: pd.DataFrame, window_start=None) -> pd.DataFrame:
    """Builds dashboard_flow_quarterly: one row per (quarter, population_segment,
    dimension, category, flow_type) — same shape and same rationale as
    build_flow_yearly_rows (see its own docstring for why experienced_homelessness/
    indiv_*/indiv_flow_* can't be reconstructed by summing dashboard_flow_monthly's
    per-month figures client-side), just grouped by calendar quarter instead
    of calendar year. `quarter` is that quarter's start date (e.g. Q3 2026 ->
    2026-07-01), matching dashboard_return_cohorts' own exit_quarter convention.

    enrollments: same contract as build_flow_rows' own `enrollments` param
    — raw, not window-scoped, used only to resolve project_engaged_*.

    A quarter whose 3 calendar months aren't ALL present in the completed-
    months window (window_start onward — see get_export_window) is skipped
    entirely, not emitted as a partial quarter: window_start always falls on
    a quarter boundary (get_export_window's start is always January 1st), so
    the only quarter this ever actually excludes is the current, still
    in-progress one — the same "no partial period" convention
    get_export_window itself already applies to months.
    """
    episodes = _add_inflow_outflow_flags(episodes)
    episodes["_quarter"] = episodes["TimePeriodStartDate"].dt.to_period("Q").dt.start_time
    all_months = sorted(episodes["TimePeriodStartDate"].unique())
    month_index = {m: i for i, m in enumerate(all_months)}
    published = episodes if window_start is None else episodes[episodes["TimePeriodStartDate"] >= window_start]

    all_categories = {
        dimension: _all_categories(published, dimension, DIMENSION_COLUMNS) for dimension in FLOW_DIMENSIONS
    }
    # EPISODE_SCOPED_CATEGORY_DIMENSIONS deliberately left out of this
    # one-time snapshot — resolved fresh per quarter below instead (see
    # _person_category_for_period).
    person_category = {
        dimension: episodes.drop_duplicates("PersonalID").set_index("PersonalID")[DIMENSION_COLUMNS[dimension]]
        for dimension in _CONSTANT_CATEGORY_DIMENSIONS
    }
    group_enrollments = _group_enrollments_by_dimension(enrollments)

    rows: list = []
    for quarter, quarter_df in published.groupby("_quarter"):
        months = sorted(quarter_df["TimePeriodStartDate"].unique())
        if len(months) < 3:
            continue
        prior_idx = month_index[months[0]] - 1
        prior_month = all_months[prior_idx] if prior_idx >= 0 else None
        period_start = pd.Timestamp(months[0])
        period_end = pd.Timestamp(months[-1]) + pd.offsets.MonthEnd(0)
        # This quarter's own category lookup — see EPISODE_SCOPED_CATEGORY_DIMENSIONS
        # and, for unsheltered_in_period/project_engaged_*, PERIOD_AGGREGATE_CATEGORY_DIMENSIONS.
        period_category = {
            **person_category,
            **{dim: _person_category_for_period(quarter_df, dim) for dim in EPISODE_SCOPED_CATEGORY_DIMENSIONS},
            "unsheltered_in_period": _unsheltered_in_period_category(quarter_df),
            **{
                dim: _project_engagement_category(quarter_df, group_enrollments[dim], period_start, period_end)
                for dim in PROJECT_ENGAGEMENT_DIMENSIONS
            },
        }

        for segment_key, pop_label in POPULATION_SEGMENTS.items():
            person_ids: set = set()
            for month in months:
                month_df = quarter_df[quarter_df["TimePeriodStartDate"] == month]
                pop_df = filter_population(month_df, pop_label, month)
                person_ids.update(pop_df["PersonalID"])

            def _add(flow_type: str, count: int, dimension: str = "overall", category: str = "Overall", extra: dict | None = None):
                row = {
                    "quarter": quarter,
                    "population_segment": segment_key,
                    "dimension": dimension,
                    "category": category,
                    "flow_type": flow_type,
                    "count": count,
                }
                if extra:
                    row.update(extra)
                rows.append(row)

            _add("experienced_homelessness", len(person_ids))
            for dimension in PARTITION_CATEGORY_DIMENSIONS:
                categories = all_categories[dimension]
                counts = (
                    period_category[dimension]
                    .reindex(list(person_ids))
                    .value_counts()
                    .reindex(categories, fill_value=0)
                    .astype(int)
                )
                for category, count in counts.items():
                    _add("experienced_homelessness", int(count), dimension=dimension, category=category)

            partition = _partition_by_individual(episodes, pop_label, months, prior_month)
            for key, ids in {**partition["inflow"], **partition["outflow"]}.items():
                _add(f"indiv_{key}", len(ids))
            for (inflow_key, outflow_key), count in partition["pairs"].items():
                _add(
                    f"indiv_flow_{inflow_key}_to_{outflow_key}",
                    count,
                    extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                )

            for dimension in PARTITION_CATEGORY_DIMENSIONS:
                categories = all_categories[dimension]
                bucket_counts, pair_counts = _partition_counts_by_category(partition, period_category[dimension], categories)
                for key, counts in bucket_counts.items():
                    for category, count in counts.items():
                        _add(f"indiv_{key}", count, dimension=dimension, category=category)
                for (inflow_key, outflow_key), counts in pair_counts.items():
                    for category, count in counts.items():
                        _add(
                            f"indiv_flow_{inflow_key}_to_{outflow_key}",
                            count,
                            dimension=dimension,
                            category=category,
                            extra={"inflow_bucket": inflow_key, "outflow_bucket": outflow_key},
                        )

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
    the race_*/gender_* rollup columns and VeteranStatus (none of which are
    native to the enrollment table itself).

    `enrollments` is expected raw (one row per enrollment span, no
    TimePeriodStartDate column — this table has no monthly grain of its own,
    unlike episode_systemwide, so the monthly panel is built here from
    ProjectStartDate/ProjectExitDate against the `months` list).
    """
    enrollments = enrollments.merge(
        client_demographics[["PersonalID", *_RACE_ROLLUP_COLUMNS, "GenderIdentity", "GenderAlignment", "VeteranStatus"]],
        on="PersonalID",
        how="left",
    )
    enrollments["_bucket"] = enrollments["ProjectTypeCode"].apply(_resource_type_bucket)
    enrollments = enrollments.dropna(subset=["_bucket"])

    # AgeTierAtEnrollment uses a different label vocabulary than
    # episode_systemwide's EpisodeAgeTier for the same buckets — confirmed
    # against the two tables' actual distinct values, not assumed: "0 to 17"
    # where EpisodeAgeTier says "Under 18", "65 or Above" where it says
    # "65+", plus an enrollment-only "Below 0" bucket for negative/bad ages
    # that EpisodeAgeTier's own age-at-episode-start computation already
    # folds into "Under 18" (age_at_start < 18 catches negative ages too —
    # see Episode_Systemwide notebook). Normalized into a NEW column (not
    # overwritten in place) so dashboard_flow_monthly's age_category
    # dimension — which mixes these enrollment-driven resource_* rows with
    # episode-driven rows under one dimension — carries a single clean
    # category set instead of two overlapping ones (this bit the frontend's
    # category dropdown directly: it showed both "65+" and "65 or Above" as
    # separate options for what's really one bucket). Raw AgeTierAtEnrollment
    # itself must stay untouched: filter_population_enrollment's YYA branch
    # compares against its literal "0 to 17" value, and normalizing it away
    # in place would silently break that population filter.
    enrollments["AgeCategory"] = enrollments["AgeTierAtEnrollment"].replace(
        {"0 to 17": "Under 18", "65 or Above": "65+", "Below 0": "Under 18"}
    )

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
