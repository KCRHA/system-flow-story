"""Small-cell suppression for public dashboard exports.

Every exported JSON file is publicly fetchable and, once pushed, effectively
permanent (a later commit can't erase what an earlier commit exposed via git
history). Two layers are applied in order, at build time, never in the
frontend:

  1. Primary threshold  — any NONZERO cell with count < SUPPRESSION_THRESHOLD
     is nulled and marked "*" (PRIMARY_SUPPRESSION_MARKER). A true zero is
     never suppressed: zero can't identify any specific person, so there's
     nothing to protect by hiding it.
  2. Secondary (complementary) suppression — primary suppression alone lets
     a reader back-compute a suppressed value by arithmetic. A second,
     otherwise-visible cell in the same group is additionally suppressed and
     marked "**" (SECONDARY_SUPPRESSION_MARKER) whenever:
       a. exactly one category in the group is primary-suppressed (its
          value could be recovered by subtracting every visible category
          from a known group total), or
       b. two or more categories are primary-suppressed and they all share
          the exact same true count, and that count is 1 or 10 — the two
          values where the [1, threshold-1] bound itself (zero is excluded,
          see above) forces every suppressed cell in the group to an
          identical, guessable number (all-1s: the minimum-possible cell;
          all-10s: the maximum-possible cell still under the threshold),
          even without knowing a group total.

     The cell picked to carry the "**" mark prefers a nonzero visible
     category over a zero one — hiding a zero achieves the same arithmetic
     protection, but there's no privacy reason to ever hide one, so it's
     only picked when every other visible category is already spoken for
     (i.e. there's no nonzero option left).

Scope: secondary suppression only protects a hidden cell from being
calculated out of the other categories in the SAME selection a reader sees
on the dashboard (one dimension's categories within one period, population
segment and flow_type; plus the sankey's own row/column/bucket totals
within one category). It deliberately does not guard against combining
numbers across different selections (overlapping dimensions, or chaining
one relationship's result into another). A group with only one category
in it (e.g. race_aian once its "Not Included" row is dropped in export.py)
never needs secondary suppression: there's nothing to calculate it from.

No rounding is applied — secondary suppression is what prevents
back-calculation, so there's nothing rounding would additionally protect
against here.

validate() is a hard gate: it returns violations rather than raising, so
export.py can print them clearly and exit(1) — this must fail the pipeline
build, not just warn.

apply_crosstab_secondary_suppression()/validate_crosstab() extend the same
rule (b above) to dashboard_flow_monthly/_yearly's indiv_flow_* cross-tab
cells (build_flow.py's _partition_by_individual): those aren't a
dimension-category breakdown, so the main pass's grouping never sees them
as siblings of each other. But every cell sharing an inflow_bucket sums to
that bucket's own published total (indiv_newly_homeless etc.), and same
for every cell sharing an outflow_bucket — a "row" and a "column" of the
cross-tab are exactly the same kind of sibling-group risk as a dimension's
categories, just keyed differently. Deliberately does NOT try to protect
against every possible arithmetic combination (e.g. a suppressed cell's
sum with specific others happening to be inferable within some range) —
per-conversation scope, only the same two cases rule (b) already commits
to: a lone suppressed cell in a row/column, or multiple that are all
forced to the same extreme (1 or 10).

apply_insufficient_population_fallback() handles the case where a group
needs secondary suppression but has no visible sibling cell left at all
(every category, or every inflow/outflow bucket, sharing that group is
already primary-suppressed) — a small enough population segment crossed
with a low-cardinality dimension (e.g. gender_alignment's 3 categories)
can genuinely leave nothing to hide behind. There is no partial fix for
that: hiding one more cell isn't possible because none is left, and
leaving the group as-is would mean its individually-masked cells are
still arithmetically recoverable from a visible total elsewhere in that
same (dimension, category) scope. So instead of a single cell, the
*entire* (period, population_segment, dimension, category) scope — every
flow_type, not just the one that triggered the check — is blanked
together with INSUFFICIENT_POPULATION_MARKER, closing off every number
in that scope at once (including whatever total made the recovery
possible) rather than leaving a gap for validate()/validate_crosstab() to
hard-fail the export over. Run this AFTER both apply_* passes above and
BEFORE validate()/validate_crosstab() — those remain the final hard gate;
under normal operation they should report zero violations once this has
run, since it's meant to resolve everything they'd otherwise catch.
"""
import time
from datetime import datetime
from functools import wraps

import numpy as np
import pandas as pd

from .config import (
    DECEASED_BAND_WIDTH,
    PRIMARY_SUPPRESSION_MARKER,
    SECONDARY_SUPPRESSION_MARKER,
    SUPPRESSION_THRESHOLD,
    UNPUBLISHED_CATEGORIES,
)

TRUE_COUNT_COL = "_true_count"  # internal only — never written to exported JSON
# Distinct from PRIMARY_SUPPRESSION_MARKER/SECONDARY_SUPPRESSION_MARKER (a
# single small cell) — this means "this whole demographic slice can't be
# safely shown," which the frontend renders as its own message rather than
# folding it into a normal per-cell "*"/"**" display.
INSUFFICIENT_POPULATION_MARKER = "insufficient_population"

# Internal only: rows in config.UNPUBLISHED_CATEGORIES, which are never
# written to the JSON (export._to_json_records drops them). Marked so every
# pass treats them as hidden cells a reader knows nothing about ("0 or
# more"): they protect their siblings, but never need protecting themselves.
UNPUBLISHED_MARKER = "unpublished"


def unpublished_rows(df: pd.DataFrame) -> pd.Series:
    """Rows in an UNPUBLISHED_CATEGORIES category of a non-overall dimension."""
    if "category" not in df.columns or "dimension" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["category"].isin(UNPUBLISHED_CATEGORIES) & (df["dimension"] != "overall")


def _timed(func):
    """Prints a timestamped line every time one of this module's public
    functions runs: which one, what scope it ran for (whichever of
    group_cols/main_group_cols/period_col the caller passed — every
    call site below passes one of these as a keyword, see export.py), how
    many rows its `df` argument had, and how long it took.

    export.py's own _checkpoint prints ONE number for a table's entire
    suppression+validate chain (e.g. "flow_df suppression+validate:
    1345.1s") — that's 5-8 of these calls lumped together, so it can't say
    which one actually ate the time. Decorating here instead of wrapping
    each call site individually means every call through every table gets
    this for free, including ones added later."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - t0
        df = args[0] if args and isinstance(args[0], pd.DataFrame) else None
        rows = len(df) if df is not None else "?"
        scope = kwargs.get("group_cols") or kwargs.get("main_group_cols") or kwargs.get("period_col")
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] suppression.{func.__name__}(rows={rows}, scope={scope}): {elapsed:.2f}s")
        return result

    return wrapper


@_timed
def apply_full_suppression_pipeline(df: pd.DataFrame, group_cols: list[str], count_col: str = "count") -> pd.DataFrame:
    df = df.copy()
    df[TRUE_COUNT_COL] = df[count_col]
    df["suppression_marker"] = None
    # > 0: a true zero is never suppressed — it can't identify a person.
    df.loc[(df[TRUE_COUNT_COL] > 0) & (df[TRUE_COUNT_COL] < SUPPRESSION_THRESHOLD), "suppression_marker"] = PRIMARY_SUPPRESSION_MARKER
    df.loc[unpublished_rows(df), "suppression_marker"] = UNPUBLISHED_MARKER

    if "dimension" in df.columns:
        eligible = df[df["dimension"] != "overall"]
    else:
        eligible = df

    picks = _secondary_picks(eligible, group_cols)
    if len(picks):
        df.loc[picks, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER

    df.loc[df["suppression_marker"].notna(), count_col] = pd.NA
    return df


def _needs_secondary(primary_suppressed_true_counts: pd.Series) -> bool:
    n = len(primary_suppressed_true_counts)
    if n == 0:
        return False
    if n == 1:
        return True
    unique_vals = primary_suppressed_true_counts.unique()
    return len(unique_vals) == 1 and unique_vals[0] in (1, 10)


def _groups_needing_secondary(df: pd.DataFrame, group_cols: list[str]) -> pd.Index:
    """Vectorized equivalent of `{key for key, group in df.groupby(group_cols)
    if _needs_secondary(group-restricted-to-PRIMARY_SUPPRESSION_MARKER[TRUE_COUNT_COL])}`
    — same "exactly one primary cell, or 2+ that are all equal to 1 or 10"
    rule, computed as one groupby().agg() over every primary-suppressed row
    at once instead of a Python-level loop re-deriving it per group. Shared
    by _secondary_picks below and validate()/validate_crosstab()'s own
    group-level check, which needs the same group set but doesn't need to
    pick a row — see each caller for why.

    Returns the group-key Index (flat Index for one group_col, MultiIndex
    for several) of every group meeting the rule — groups with ZERO
    primary-suppressed rows never appear in `primary` at all (groupby
    only emits groups that have >=1 member), matching
    `_needs_secondary([]) -> False`'s implicit exclusion."""
    primary = df[df["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
    if primary.empty:
        return pd.MultiIndex.from_arrays([[] for _ in group_cols]) if len(group_cols) > 1 else pd.Index([])
    stats = primary.groupby(group_cols, dropna=False)[TRUE_COUNT_COL].agg(["size", "nunique", "first"])
    needs_secondary = (stats["size"] == 1) | ((stats["size"] > 1) & (stats["nunique"] == 1) & stats["first"].isin([1, 10]))
    # A group with only one member has no sibling to calculate it from
    # (e.g. a race_* dimension, whose only published category is
    # "Included"), so it never needs secondary suppression.
    group_sizes = df.groupby(group_cols, dropna=False).size()
    has_siblings = group_sizes.reindex(stats.index).fillna(0) > 1
    return stats.index[needs_secondary & has_siblings.to_numpy()]


def _group_keys(df: pd.DataFrame, group_cols: list[str]):
    """One array-like key per row of `df`, for grouping by an externally-
    computed key (e.g. a boolean mask already applied) without losing the
    original index the way `.merge()` would — `Series.groupby(by=...)` and
    `Index.isin(...)` both accept this directly. A flat Index for one
    group_col (matching that single column's own values), a MultiIndex for
    several (matching what `.groupby(group_cols).groups` keys on)."""
    if len(group_cols) == 1:
        return pd.Index(df[group_cols[0]])
    return pd.MultiIndex.from_frame(df[group_cols])


def _secondary_picks(df: pd.DataFrame, group_cols: list[str]) -> pd.Index:
    """Vectorized equivalent of looping `for _, group in df.groupby(group_cols):
    if _needs_secondary(...): _pick_secondary(df, group, count_col)` — the
    exact row-index each such call would have picked (same preference order:
    restrict to nonzero-visible candidates if the group has any, smallest
    TRUE_COUNT_COL among whatever's left, ties broken by original row
    order), computed via groupby aggregations instead of a Python-level
    loop over every group.

    Only valid when every group in `group_cols` is independent of every
    other — true here and in apply_full_suppression_pipeline's own call,
    since group_cols fully partitions `df`'s rows into disjoint groups and
    a pick only ever reads/writes rows already scoped to its own group. NOT
    reused by apply_crosstab_secondary_suppression's own
    _resolve_crosstab_period: there, a single pick can satisfy both a row's
    and a column's need at once, so picks must be resolved jointly and
    sequentially, not independently per group — see that function's own
    docstring. Groups already protected (see _groups_with_protection, e.g.
    by an unpublished "Unknown" sibling) get no pick."""
    needing = _violating_groups(df, group_cols)
    if len(needing) == 0:
        return pd.Index([])

    visible = df[df["suppression_marker"].isna() & df[TRUE_COUNT_COL].notna()]
    if visible.empty:
        return pd.Index([])
    visible_keys = _group_keys(visible, group_cols)
    in_needing = visible_keys.isin(needing)
    if not in_needing.any():
        return pd.Index([])
    visible = visible[in_needing]
    visible_keys = visible_keys[in_needing]

    # Prefer hiding a nonzero cell: restrict each group to its nonzero
    # visible rows if it has any, and only fall back to hiding a zero when
    # nothing else is left (a hidden zero protects the primary cell just as
    # well, but there's no privacy reason to hide one otherwise). So "**"
    # doesn't promise 11+; it can be any value, including 0.
    is_nonzero = visible[TRUE_COUNT_COL] > 0
    group_has_nonzero = is_nonzero.groupby(visible_keys).transform("any")
    is_candidate = ((~group_has_nonzero) | is_nonzero).to_numpy()
    candidates = visible[is_candidate]
    candidate_keys = visible_keys[is_candidate]
    if candidates.empty:
        return pd.Index([])

    picks = candidates.groupby(candidate_keys)[TRUE_COUNT_COL].idxmin()
    return pd.Index(picks.to_numpy())


def _groups_with_protection(df: pd.DataFrame, group_cols: list[str]) -> pd.Index:
    """Group keys (same Index/MultiIndex shape _groups_needing_secondary
    returns) that already have >=1 SECONDARY_SUPPRESSION_MARKER/
    INSUFFICIENT_POPULATION_MARKER/UNPUBLISHED_MARKER row — all count as
    protection: each is a hidden sibling a reader can't subtract out.

    An unpublished cell only counts when its true count is above 0. A zero
    "Unknown" hides nothing: where Unknown is always 0, the published
    categories add up exactly to overall, a reader sees that, and a lone
    "*" next to it is as recoverable as if Unknown weren't there. (A
    nonzero one also rules out the all-1s case: the hidden cells then add
    up to more than the number of "*" cells.)"""
    empty = pd.MultiIndex.from_arrays([[] for _ in group_cols]) if len(group_cols) > 1 else pd.Index([])
    marker = df["suppression_marker"]
    protected = df[
        marker.isin([SECONDARY_SUPPRESSION_MARKER, INSUFFICIENT_POPULATION_MARKER])
        | ((marker == UNPUBLISHED_MARKER) & (df[TRUE_COUNT_COL] > 0))
    ]
    if protected.empty:
        return empty
    return protected.groupby(group_cols, dropna=False).size().index


def _violating_groups(df: pd.DataFrame, group_cols: list[str]) -> pd.Index:
    """Group keys needing secondary suppression but with none in place —
    the exact hard-gate check validate()/validate_crosstab()/
    validate_sankey_marginal() all share, computed via groupby
    aggregations (_groups_needing_secondary/_groups_with_protection above)
    instead of a Python-level loop over every group. The resulting Index
    is normally empty (or very small) on a healthy export — only an actual
    violation lands here, so the handful of remaining call sites that
    build a message per entry stay a plain Python loop, just over this
    tiny set instead of every group that exists."""
    needing = _groups_needing_secondary(df, group_cols)
    if len(needing) == 0:
        return needing
    return needing.difference(_groups_with_protection(df, group_cols))


@_timed
def apply_return_count_suppression(
    df: pd.DataFrame,
    group_cols: list[str],
    count_col: str,
    marker_col: str,
    extra_cols: list[str] = (),
) -> tuple[pd.DataFrame, list[str]]:
    """Primary and secondary suppression for a derived count that's
    independently small-cell-risky from whatever the table's own
    `suppression_marker` already protects — e.g. dashboard_return_cohorts'
    n_returned, which can be small even when n_exited (the row's main
    suppression key) is well above threshold: plenty of people can exit to
    permanent housing in a quarter while only a handful of them return.

    `count_col` needs the same complementary protection as every other
    count here: each dimension's categories sum to the "overall" row, so a
    lone hidden value is recoverable by subtraction. Run AFTER the table's
    main suppression, with `count_col` already nulled on every row carrying
    a `suppression_marker`. `group_cols` is the same list passed to
    apply_full_suppression_pipeline.

    A row hidden by `suppression_marker` hides its `count_col` too, but that
    doesn't make it protection on its own: its value is still the overall
    minus every visible category. So it's treated by its own true value: a
    1-10 counts as primary (it needs a sibling hidden too, and it counts
    toward the all-1s/all-10s rule), 11+ counts as a secondary that's
    already in place, and a zero is ignored (a recovered zero identifies
    nobody).

    Uses its own `marker_col`, separate from the table's `suppression_marker`
    — a row can have a perfectly safe-to-show n_exited while still needing
    this, so it shouldn't be forced to hide the whole row the way a
    `suppression_marker` hit does. `extra_cols` (e.g. a percentage derived
    from `count_col`) are blanked alongside it.

    A group left with nothing visible to hide behind is marked
    INSUFFICIENT_POPULATION_MARKER rather than reported as a violation —
    see _suppress_capacity_household_count for why that hides nothing new.

    Returns the suppressed df plus any violations, for the caller to fold
    into the pipeline's usual hard gate.
    """
    work = df.copy()
    row_hidden = work["suppression_marker"].notna()
    work[TRUE_COUNT_COL] = work[count_col]
    work["suppression_marker"] = None
    work.loc[row_hidden & (work[count_col] >= SUPPRESSION_THRESHOLD), "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER
    is_primary = (work[count_col] > 0) & (work[count_col] < SUPPRESSION_THRESHOLD)
    work.loc[is_primary, "suppression_marker"] = PRIMARY_SUPPRESSION_MARKER
    work.loc[df["suppression_marker"] == UNPUBLISHED_MARKER, "suppression_marker"] = UNPUBLISHED_MARKER

    eligible = work[work["dimension"] != "overall"]
    unprotected = _violating_groups(eligible, group_cols)
    if len(unprotected):
        picks = _secondary_picks(eligible[_group_keys(eligible, group_cols).isin(unprotected)], group_cols)
        work.loc[picks, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER

    eligible = work[work["dimension"] != "overall"]
    unresolved = _violating_groups(eligible, group_cols)
    if len(unresolved):
        in_unresolved = _group_keys(eligible, group_cols).isin(unresolved) & (eligible["suppression_marker"] != UNPUBLISHED_MARKER).to_numpy()
        work.loc[eligible.index[in_unresolved], "suppression_marker"] = INSUFFICIENT_POPULATION_MARKER

    violations = []
    for key in _violating_groups(work[work["dimension"] != "overall"], group_cols):
        key_dict = dict(zip(group_cols, key if isinstance(key, tuple) else (key,)))
        violations.append(f"{count_col} group {key_dict} needs secondary suppression but has none")

    df = df.copy()
    # Rows already hidden by suppression_marker keep marker_col empty — the
    # whole row is withheld, not just this count.
    df[marker_col] = work["suppression_marker"].where(~row_hidden, None)
    df.loc[df[marker_col].notna() | row_hidden, [count_col, *extra_cols]] = None
    return df, violations


def _pick_secondary(df: pd.DataFrame, group: pd.DataFrame, count_col: str) -> None:
    """Shared by apply_sankey_marginal_suppression and
    apply_crosstab_secondary_suppression: given a group that
    _needs_secondary(...), marks one more visible cell in it, mutating
    `df` in place. No-op if the group has nothing left to hide (already
    fully suppressed some other way)."""
    visible = group[group["suppression_marker"].isna()].dropna(subset=[TRUE_COUNT_COL])
    if visible.empty:
        return
    # Prefer a nonzero cell, fall back to a zero — see _secondary_picks.
    nonzero_visible = visible[visible[TRUE_COUNT_COL] > 0]
    candidates = nonzero_visible if not nonzero_visible.empty else visible
    next_smallest_idx = candidates[TRUE_COUNT_COL].idxmin()
    df.loc[next_smallest_idx, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER


@_timed
def apply_crosstab_secondary_suppression(df: pd.DataFrame, group_cols: list[str], count_col: str = "count") -> pd.DataFrame:
    """Run AFTER apply_full_suppression_pipeline (needs its primary markers
    and TRUE_COUNT_COL already in place) on the same df. `group_cols`
    should be the period+population identifiers only (e.g.
    ["month", "population_segment"] or ["year", "population_segment"]) —
    row/column grouping here is keyed by inflow_bucket/outflow_bucket
    instead of dimension/flow_type. Rows without those two columns set
    (i.e. every flow_type except indiv_flow_*) are left untouched.

    Resolves both axes (rows = inflow_bucket, columns = outflow_bucket)
    JOINTLY within each period, not as two independent sequential passes
    — see _resolve_crosstab_period for why: a rare category (e.g.
    "aged_out," which tends to be the smallest value in many rows at
    once for a small population segment) can otherwise get greedily
    claimed as several different rows' own secondary pick before its own
    column ever gets a turn, leaving that column's own primary-suppressed
    cell with nothing left to hide behind, even though a valid assignment
    existed.
    """
    if "inflow_bucket" not in df.columns:
        return df
    df = df.copy()
    is_pair = df["inflow_bucket"].notna()

    for _, period_index in df[is_pair].groupby(group_cols, dropna=False).groups.items():
        _resolve_crosstab_period(df, period_index, count_col)

    df.loc[is_pair & df["suppression_marker"].notna(), count_col] = pd.NA
    return df


@_timed
def apply_sankey_marginal_suppression(
    df: pd.DataFrame,
    group_cols: list[str],
    bucket_flow_type_groups: list[list[str]],
    total_flow_type: str = "experienced_homelessness",
    count_col: str = "count",
) -> pd.DataFrame:
    """Run AFTER apply_full_suppression_pipeline (needs its primary markers
    and TRUE_COUNT_COL already in place) on the same df, alongside
    apply_crosstab_secondary_suppression. `group_cols` is the period +
    population identifier only (e.g. ["month", "population_segment"]).

    The sankey's inflow buckets (already_active/newly_homeless/
    return_from_housed/return_from_inactive, published as their indiv_*
    flow_types) are a true partition of experienced_homelessness, and so
    are its outflow buckets (still_active/aged_out/permanently_housed/
    inactive, deceased included) — see build_flow.py's _partition_by_individual
    docstring. Both sets exist for every (dimension, category), not just
    overall: picking a category on the dashboard shows that category's own
    sankey, whose buckets add up to that category's own
    experienced_homelessness. So this runs once per (group_cols, dimension,
    category). That's the same "exactly one suppressed cell is recoverable
    from its siblings plus a known group total" risk
    apply_full_suppression_pipeline's own main loop already guards against
    for demographic categories — but flow_type is part of THAT loop's own
    group_cols, so every indiv_* row lands in its own single-row group
    there. Nothing else in the pipeline treats these flow_types as siblings
    of each other, so this gets its own pass.

    `total_flow_type`'s own row is folded into each bucket group as an
    extra member, not just referenced conceptually: a small, suppressed
    total is just as recoverable (by summing fully-visible buckets) as a
    suppressed bucket is from a visible total, so it's equally at risk and
    equally eligible to be the one `_pick_secondary` hides.
    """
    df = df.copy()
    cols = [*group_cols, "dimension", "category"]
    is_total = df["flow_type"] == total_flow_type
    # Inflow first, then outflow: both share the total row, so an inflow
    # pick that lands on the total already protects the outflow group, and
    # _violating_groups below sees it.
    for flow_types in bucket_flow_type_groups:
        scoped = df[df["flow_type"].isin(flow_types) | is_total]
        unprotected = _violating_groups(scoped, cols)
        if len(unprotected) == 0:
            continue
        picks = _secondary_picks(scoped[_group_keys(scoped, cols).isin(unprotected)], cols)
        df.loc[picks, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER

    df.loc[df["suppression_marker"].notna(), count_col] = pd.NA
    return df


def _resolve_crosstab_period(df: pd.DataFrame, period_index, count_col: str) -> None:
    """Jointly resolves every inflow_bucket ("row") and outflow_bucket
    ("column") group within one (group_cols) period at once, mutating
    `df` in place. Always picks for the currently most-constrained
    still-resolvable group (fewest visible candidates) first, so a
    nearly-exhausted group locks in its pick before a less-constrained one
    can spend a shared cell on a cheaper choice of its own — and
    re-derives live suppression state from `df` after every pick (not a
    stale groupby snapshot), since a single pick can satisfy both a row's
    and a column's need at once when it sits at their intersection.

    A group with zero visible candidates left is skipped, not treated as
    a reason to give up on the whole period — one genuinely unresolvable
    group (validate_crosstab will surface it) shouldn't block every other,
    resolvable group in the same period from getting its own protection.

    Tried replacing the full re-derive above with incremental state
    (refresh only the 1-2 groups touched by each pick, instead of
    regrouping the whole period from scratch every time) — measured
    SLOWER at realistic scale (46.8s vs 36.0s on a 90k-row/4,536-period
    synthetic benchmark), not faster. A period here typically has very
    few groups (at most 4 inflow + 5 outflow buckets) and needs at most a
    handful of picks, so the full re-derive was already cheap; building
    the extra bookkeeping (per-group row-index maps, order-index for
    tie-breaking, etc.) once per period, across however many thousands of
    periods a table has, cost more than it saved. The real cost of
    apply_crosstab_secondary_suppression is the sheer NUMBER of periods
    this gets called once per — not how each individual period is
    resolved — which this approach doesn't address. Left as the simpler
    version on purpose.
    """
    given_up: set = set()
    while True:
        period_df = df.loc[period_index]
        needing = []
        for axis_col in ("inflow_bucket", "outflow_bucket"):
            for key, group in period_df.groupby(axis_col, dropna=False):
                if (axis_col, key) in given_up:
                    continue
                primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
                has_secondary = (group["suppression_marker"] == SECONDARY_SUPPRESSION_MARKER).any()
                if _needs_secondary(primary[TRUE_COUNT_COL]) and not has_secondary:
                    visible = group[group["suppression_marker"].isna()].dropna(subset=[TRUE_COUNT_COL])
                    needing.append((len(visible), axis_col, key, group))
        if not needing:
            return
        needing.sort(key=lambda t: t[0])
        candidate_count, axis_col, key, group = needing[0]
        if candidate_count == 0:
            # Nothing left anywhere in this group to hide behind — no pick
            # can resolve it. Leave it for validate_crosstab to surface as
            # a real violation, but keep trying the period's other,
            # still-resolvable groups instead of aborting on all of them.
            given_up.add((axis_col, key))
            continue
        _pick_secondary(df, group, count_col)


@_timed
def apply_insufficient_population_fallback(
    df: pd.DataFrame,
    period_col: str,
    main_group_cols: list[str],
    crosstab_group_cols: list[str],
    count_col: str = "count",
    sankey_bucket_flow_type_groups: list[list[str]] = (),
    sankey_total_flow_type: str = "experienced_homelessness",
) -> pd.DataFrame:
    """Run AFTER apply_full_suppression_pipeline and (if the table has
    indiv_flow_* rows) apply_crosstab_secondary_suppression and (if the
    table has a sankey) apply_sankey_marginal_suppression, on the same
    df. `main_group_cols`/`crosstab_group_cols` are exactly the group_cols
    you're about to pass to validate()/validate_crosstab() — this reuses
    the identical grouping so it resolves precisely what those would
    otherwise flag. `sankey_bucket_flow_type_groups`/`sankey_total_flow_type`
    are the same arguments passed to apply_sankey_marginal_suppression/
    validate_sankey_marginal; pass them (non-empty) only for a table that
    has a sankey.

    For a main-pass group (flow_type-keyed, spans every category of one
    dimension): if unresolved, every category with a primary-suppressed
    cell in it is implicated — there's no partial answer, since a
    non-implicated category would always have been available as a
    sibling to hide behind (see apply_full_suppression_pipeline), so
    "unresolved" here only happens when literally every category is
    already suppressed. Only THAT flow_type gets blanked for those
    categories — every other flow_type in the same (dimension, category)
    is a completely separate group with its own, independent suppression
    state, and is left alone.

    For a crosstab group (row/column-keyed, already scoped to one exact
    category via crosstab_group_cols): the implicated category is the
    group's own category value directly. Blanked here: every
    indiv_flow_* cell sharing that row/column (the group itself), PLUS
    that row/column's own published total flow_type (e.g. indiv_aged_out
    for an outflow_bucket="aged_out" column, indiv_newly_homeless for an
    inflow_bucket="newly_homeless" row) — a visible total is exactly what
    would make the hidden cells in that row/column arithmetically
    recoverable, so closing it off is what actually resolves the
    vulnerability. Every OTHER flow_type for that same (dimension,
    category) — active_total, experienced_homelessness, an unrelated
    row/column's own cells, etc. — has nothing to do with this specific
    row/column and is left alone: a large, well-populated category (e.g.
    a common race) can easily have one narrow, naturally-small crosstab
    slice (like a specific inflow reason crossed with "Aged Out") without
    the category's other, unrelated numbers needing to go dark too.

    For a sankey-marginal group (one of `sankey_bucket_flow_type_groups`
    plus `sankey_total_flow_type`, all at dimension="overall"/
    category="Overall" — see apply_sankey_marginal_suppression): if
    unresolved, every flow_type in that specific bucket-and-total group is
    blanked together, the same closing-off logic as the crosstab case
    above. The sankey's OTHER bucket group for the same period (e.g.
    outflow, when inflow is what's unresolved) shares only the total row
    with this one and is left alone unless it independently needs it.
    """
    df = df.copy()
    if "dimension" not in df.columns or "category" not in df.columns:
        return df
    has_flow_type = "flow_type" in df.columns
    # length/return-cohort tables have no flow_type column at all (each row
    # already IS one specific measurement) — every other table's blank
    # keys carry the specific flow_type so blanking stays scoped to it, not
    # every flow_type sharing the same (dimension, category).
    key_cols = [period_col, "population_segment", "dimension", "category"] + (["flow_type"] if has_flow_type else [])

    # Each block below finds its own unresolved (`_violating_groups`)
    # groups and collects the exact rows `_key(...)`'s original per-group
    # Python loop would have turned into blank_keys tuples — but reads
    # those tuples' fields straight off each implicated row's own columns
    # (which already carry its group's key_cols values, group membership
    # being exactly what made them constant within the group) instead of
    # reconstructing them from a group key dict. One groupby-based pass
    # per block replaces that block's own per-group Python loop; the
    # `pd.concat(...).drop_duplicates()` below replaces blank_keys' own
    # dedup role.
    blank_frames: list[pd.DataFrame] = []

    eligible = df[df["dimension"] != "overall"]
    violating = _violating_groups(eligible, main_group_cols)
    if len(violating):
        row_keys = _group_keys(eligible, main_group_cols)
        is_implicated = row_keys.isin(violating) & (eligible["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER).to_numpy()
        implicated = eligible[is_implicated]
        if not implicated.empty:
            blank_frames.append(implicated[key_cols])

    if "inflow_bucket" in df.columns:
        is_pair = df["inflow_bucket"].notna()
        pair_df = df[is_pair]
        for axis_col in ("inflow_bucket", "outflow_bucket"):
            cols = [*crosstab_group_cols, axis_col]
            violating = _violating_groups(pair_df, cols)
            if len(violating) == 0:
                continue
            row_keys = _group_keys(pair_df, cols)
            violating_rows = pair_df[row_keys.isin(violating)]
            if violating_rows.empty:
                continue
            # Every indiv_flow_* cell sharing this row/column...
            blank_frames.append(violating_rows[key_cols])
            # ...PLUS that row/column's own published total flow_type (one
            # row per violating GROUP, not per row — cols is exactly this
            # group's key, so dropping duplicates on it collapses each
            # group back to the single row _key(...)'s own version used).
            totals = violating_rows.drop_duplicates(subset=cols)[[period_col, "population_segment", "dimension", "category", axis_col]].copy()
            totals["flow_type"] = "indiv_" + totals[axis_col].astype(str)
            blank_frames.append(totals[key_cols])

    if sankey_bucket_flow_type_groups:
        is_total = df["flow_type"] == sankey_total_flow_type
        cols = [period_col, "population_segment", "dimension", "category"]
        for flow_types in sankey_bucket_flow_type_groups:
            scoped = df[df["flow_type"].isin(flow_types) | is_total]
            violating = _violating_groups(scoped, cols)
            if len(violating) == 0:
                continue
            violating_rows = scoped[_group_keys(scoped, cols).isin(violating)]
            if not violating_rows.empty:
                blank_frames.append(violating_rows[key_cols])

    if not blank_frames:
        return df

    blank_df = pd.concat(blank_frames, ignore_index=True).drop_duplicates()
    blank_df["_blank"] = True
    merged = df.merge(blank_df, on=key_cols, how="left")
    mask = merged["_blank"].fillna(False).to_numpy() & (df["suppression_marker"] != UNPUBLISHED_MARKER).to_numpy()
    df.loc[mask, "suppression_marker"] = INSUFFICIENT_POPULATION_MARKER
    df.loc[mask, count_col] = pd.NA
    return df


@_timed
def validate_crosstab(df: pd.DataFrame, group_cols: list[str]) -> list[str]:
    """Companion to apply_crosstab_secondary_suppression — same hard-gate
    contract as validate(). Call alongside it, not instead of it (this
    only checks the row/column groups, not the general suppression
    invariants validate() already covers)."""
    if "inflow_bucket" not in df.columns:
        return []
    violations = []
    is_pair = df["inflow_bucket"].notna()
    pair_df = df[is_pair]
    for axis_col in ("inflow_bucket", "outflow_bucket"):
        cols = [*group_cols, axis_col]
        for key in _violating_groups(pair_df, cols):
            key_dict = dict(zip(cols, key if isinstance(key, tuple) else (key,)))
            violations.append(f"crosstab group {key_dict} needs secondary suppression but has none")
    return violations


@_timed
def validate_sankey_marginal(
    df: pd.DataFrame,
    group_cols: list[str],
    bucket_flow_type_groups: list[list[str]],
    total_flow_type: str = "experienced_homelessness",
) -> list[str]:
    """Companion to apply_sankey_marginal_suppression — same hard-gate
    contract as validate(). Call alongside it, not instead of it."""
    violations = []
    cols = [*group_cols, "dimension", "category"]
    is_total = df["flow_type"] == total_flow_type
    for flow_types in bucket_flow_type_groups:
        scoped = df[df["flow_type"].isin(flow_types) | is_total]
        for key in _violating_groups(scoped, cols):
            key_dict = dict(zip(cols, key if isinstance(key, tuple) else (key,)))
            violations.append(f"sankey marginal group {key_dict} (flow_types={flow_types}) needs secondary suppression but has none")
    return violations


@_timed
def validate(df: pd.DataFrame, group_cols: list[str], count_col: str = "count") -> list[str]:
    """Returns a list of human-readable violations; an empty list means the
    export is safe to publish. Called as a hard gate in export.py — the
    build must fail (non-zero exit), not just warn, on any violation."""
    violations = []

    below_threshold_unmarked = df[
        (df["suppression_marker"].isna()) & (df[TRUE_COUNT_COL] > 0) & (df[TRUE_COUNT_COL] < SUPPRESSION_THRESHOLD)
    ]
    for _, row in below_threshold_unmarked.iterrows():
        violations.append(f"true count {row[TRUE_COUNT_COL]} below threshold but not marked suppressed: {row.to_dict()}")

    marked_with_value = df[df["suppression_marker"].notna() & df[count_col].notna()]
    for _, row in marked_with_value.iterrows():
        violations.append(f"row marked suppressed but count is not null: {row.to_dict()}")

    if "dimension" in df.columns:
        eligible = df[df["dimension"] != "overall"]
    else:
        eligible = df
    for key in _violating_groups(eligible, group_cols):
        key_dict = dict(zip(group_cols, key if isinstance(key, tuple) else (key,)))
        violations.append(f"group {key_dict} needs secondary suppression (single suppressed cell, or multiple suppressed cells all equal to 1 or 10) but has none")

    return violations


# --------------------------------------------------------------------------
# Deceased-in-inactive bands
#
# The flow tables fold deceased into inactive (config.FLOW_OUTFLOW_BUCKET_MAP).
# How many of an inactive count are deceased is published separately, per
# (period, population_segment, dimension, category), as one of:
#   - count 0 (no marker): nobody in it died. Zero is never suppressed.
#   - DECEASED_RANGE_MARKER with count_low/count_high: a fixed band of
#     config.DECEASED_BAND_WIDTH (1-10, 11-20, ...) holding the true count.
#     A band is fixed by the true count alone, so showing it says nothing
#     about the cells around it.
#   - DECEASED_WITHHELD_MARKER: at least one, number withheld. Used when the
#     combined inactive cell is hidden by anything but a primary marker (a
#     band could tighten what a reader knows about that hidden cell, and so
#     about its sankey neighbors), and for bands the check below finds a
#     reader could narrow to one value.
#   - INSUFFICIENT_POPULATION_MARKER: the inactive cell's whole slice is
#     blanked, so this is too.
# Never derivable: inactive alone is never published, and the combined
# count minus a band of 10 still leaves a span of 10.
#
# What a band CAN leak is through categories adding up: overall "1-10"
# with ten categories each "1-10" pins every category to exactly 1. Each
# dimension's categories-vs-overall relationship is checked on its own
# (only where the true categories add up to overall exactly), and every
# band in one that pins a small value is withheld.
# --------------------------------------------------------------------------

DECEASED_RANGE_MARKER = "range"
DECEASED_WITHHELD_MARKER = "withheld"
DECEASED_LOW_COL = "count_low"
DECEASED_HIGH_COL = "count_high"
# Internal only: the most the combined inactive cell can be, from what's
# published about it ("*" means 10 at most). A deceased count can't exceed
# it, so the checks below use it as a reader would.
DECEASED_COMBINED_HIGH_COL = "_combined_high"


def deceased_band(true_counts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(low, high) of the DECEASED_BAND_WIDTH band holding each count >= 1."""
    low = np.floor((true_counts - 1) / DECEASED_BAND_WIDTH) * DECEASED_BAND_WIDTH + 1
    return low, low + DECEASED_BAND_WIDTH - 1


def _combined_high(flow_df: pd.DataFrame, keys: list[str], lookup: pd.DataFrame, combined_flow_type: str, count_col: str):
    """(marker, high, found) of each `lookup` row's combined inactive cell:
    its marker as published, and the most a reader knows it can be (the
    count if visible, SUPPRESSION_THRESHOLD - 1 for "*", unbounded otherwise)."""
    rows = flow_df[flow_df["flow_type"] == combined_flow_type]
    marker = rows["suppression_marker"].to_numpy(dtype=object)
    count = pd.to_numeric(rows[count_col], errors="coerce").to_numpy(dtype=float)
    high = np.where(pd.isna(marker) & ~np.isnan(count), count, np.inf)
    high[marker == PRIMARY_SUPPRESSION_MARKER] = SUPPRESSION_THRESHOLD - 1
    combined = pd.DataFrame({"marker": marker, "high": high}, index=pd.MultiIndex.from_frame(rows[keys]))
    index = pd.MultiIndex.from_frame(lookup[keys])
    found = index.isin(combined.index)
    combined = combined.reindex(index)
    return combined["marker"].to_numpy(dtype=object), combined["high"].to_numpy(dtype=float), found


def _deceased_bounds(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """What a reader knows about each deceased count from the published data."""
    marker = df["suppression_marker"].to_numpy(dtype=object)
    count = pd.to_numeric(df["count"], errors="coerce").to_numpy(dtype=float)
    exact = ~np.isnan(count) & pd.isna(marker)
    lo = np.where(exact, count, 0.0)
    hi = np.where(exact, count, np.inf)
    is_range = marker == DECEASED_RANGE_MARKER
    lo[is_range] = df.loc[is_range, DECEASED_LOW_COL].astype(float).to_numpy()
    hi[is_range] = df.loc[is_range, DECEASED_HIGH_COL].astype(float).to_numpy()
    lo[marker == DECEASED_WITHHELD_MARKER] = 1.0
    # An unpublished "Unknown" is "0 or more", except a true zero, which is
    # treated as known (see _groups_with_protection for why).
    known_zero = (marker == UNPUBLISHED_MARKER) & (df[TRUE_COUNT_COL].to_numpy(dtype=float) == 0)
    hi[known_zero] = 0.0
    hi = np.minimum(hi, df[DECEASED_COMBINED_HIGH_COL].astype(float).fillna(np.inf).to_numpy())
    return lo, hi


def _deceased_relationships(df: pd.DataFrame, period_col: str) -> list[tuple[int, list[int], str]]:
    """(overall position, category positions, dimension) for every
    dimension's categories-vs-overall relationship among the deceased rows
    whose true categories add up to the true overall exactly."""
    true = df[TRUE_COUNT_COL].to_numpy(dtype=float)
    scope = [period_col, "population_segment"]
    is_overall = (df["dimension"] == "overall").to_numpy()
    overall_pos = {key: pos for pos, key in zip(np.flatnonzero(is_overall), df.loc[is_overall, scope].itertuples(index=False, name=None))}
    rels = []
    parts = df[~is_overall]
    for (*key, dimension), group in parts.groupby([*scope, "dimension"], sort=False):
        total = overall_pos.get(tuple(key))
        if total is None:
            continue
        pos = [df.index.get_loc(i) for i in group.index]
        if abs(true[pos].sum() - true[total]) < 1e-6:
            rels.append((total, pos, dimension))
    return rels


def _pinned_deceased(df: pd.DataFrame, rels: list) -> list[tuple[int, int]]:
    """(position, index into `rels`) of each deceased row whose true count is 1-10,
    published as a band or withheld, that one relationship's published
    bounds pin to a single value."""
    lo, hi = _deceased_bounds(df)
    true = df[TRUE_COUNT_COL].to_numpy(dtype=float)
    hidden = df["suppression_marker"].isin([DECEASED_RANGE_MARKER, DECEASED_WITHHELD_MARKER]).to_numpy()
    pinned = []
    for r, (total, parts, _dimension) in enumerate(rels):
        p_lo, p_hi = lo[parts], hi[parts]
        sum_lo = p_lo.sum()
        n_inf = int(np.isinf(p_hi).sum())
        sum_hi_finite = p_hi[~np.isinf(p_hi)].sum()
        candidates = [(total, max(lo[total], sum_lo), min(hi[total], np.inf if n_inf else sum_hi_finite))]
        for i, p in enumerate(parts):
            others_lo = sum_lo - p_lo[i]
            others_inf = n_inf - int(np.isinf(p_hi[i]))
            others_hi = np.inf if others_inf else sum_hi_finite - (0.0 if np.isinf(p_hi[i]) else p_hi[i])
            candidates.append((p, max(lo[p], lo[total] - others_hi), min(hi[p], hi[total] - others_lo)))
        for p, x_lo, x_hi in candidates:
            if hidden[p] and 0 < true[p] < SUPPRESSION_THRESHOLD and x_hi - x_lo < 0.5:
                pinned.append((p, r))
    return pinned


@_timed
def apply_deceased_bands(
    df: pd.DataFrame,
    flow_df: pd.DataFrame,
    period_col: str,
    combined_flow_type: str = "indiv_inactive",
    count_col: str = "count",
) -> pd.DataFrame:
    """`df`: one flow table's config.DECEASED_IN_INACTIVE_FLOW_TYPE rows,
    with their true counts and no suppression applied. `flow_df`: the same
    table's other rows, after every suppression pass (so each
    `combined_flow_type` row's marker is final). Returns `df` published as
    described in the section comment above, with TRUE_COUNT_COL and
    DECEASED_COMBINED_HIGH_COL kept for validate_deceased_bands."""
    df = df.reset_index(drop=True).copy()
    true = pd.to_numeric(df[count_col], errors="coerce").to_numpy(dtype=float)
    df[TRUE_COUNT_COL] = true
    keys = [period_col, "population_segment", "dimension", "category"]

    comb_marker, comb_high, found = _combined_high(flow_df, keys, df, combined_flow_type, count_col)
    df[DECEASED_COMBINED_HIGH_COL] = comb_high

    zero = true == 0
    unpublished = unpublished_rows(df).to_numpy()
    insufficient = comb_marker == INSUFFICIENT_POPULATION_MARKER
    comb_hidden = pd.notna(comb_marker) & (comb_marker != PRIMARY_SUPPRESSION_MARKER)
    withheld = ~found | comb_hidden

    marker = np.full(len(df), None, dtype=object)
    count = np.full(len(df), np.nan)
    band_lo, band_hi = deceased_band(true)
    marker[~zero] = DECEASED_RANGE_MARKER
    marker[~zero & withheld] = DECEASED_WITHHELD_MARKER
    marker[insufficient] = INSUFFICIENT_POPULATION_MARKER
    # Unpublished rows still sit in their dimension's relationship below,
    # as a "0 or more" member (see _deceased_bounds).
    marker[unpublished] = UNPUBLISHED_MARKER
    count[zero & pd.isna(marker)] = 0
    is_range = marker == DECEASED_RANGE_MARKER

    df["suppression_marker"] = marker
    df[count_col] = count
    df[DECEASED_LOW_COL] = np.where(is_range, band_lo, np.nan)
    df[DECEASED_HIGH_COL] = np.where(is_range, band_hi, np.nan)

    rels = _deceased_relationships(df, period_col)
    while True:
        pinned = _pinned_deceased(df, rels)
        if not pinned:
            break
        # Withhold every band in each relationship that pins something:
        # the categories' first, keeping the overall one (shared by every
        # dimension's relationship) unless nothing else is left.
        to_withhold = set()
        for r in {r for _, r in pinned}:
            total, parts, _dimension = rels[r]
            ranged = [p for p in parts if df.at[p, "suppression_marker"] == DECEASED_RANGE_MARKER]
            if not ranged and df.at[total, "suppression_marker"] == DECEASED_RANGE_MARKER:
                ranged = [total]
            to_withhold.update(ranged)
        if not to_withhold:
            break  # validate_deceased_bands reports it
        idx = sorted(to_withhold)
        df.loc[idx, "suppression_marker"] = DECEASED_WITHHELD_MARKER
        df.loc[idx, [DECEASED_LOW_COL, DECEASED_HIGH_COL]] = np.nan

    df[DECEASED_LOW_COL] = df[DECEASED_LOW_COL].round().astype("Int64")
    df[DECEASED_HIGH_COL] = df[DECEASED_HIGH_COL].round().astype("Int64")
    return df


@_timed
def validate_deceased_bands(df: pd.DataFrame, flow_df: pd.DataFrame, period_col: str, combined_flow_type: str = "indiv_inactive") -> list[str]:
    """Hard gate for apply_deceased_bands, same contract as validate().
    Checks, using the true counts:
      - no nonzero count is published as a number;
      - every band is a DECEASED_BAND_WIDTH band holding the true count;
      - a band only appears where the combined inactive cell is visible or
        primary-suppressed;
      - no deceased count of 1-10 can be pinned to one value from a single
        dimension's categories-vs-overall relationship."""
    violations = []
    true = df[TRUE_COUNT_COL]
    marker = df["suppression_marker"]
    shown = marker.isna()
    for idx in df.index[shown & (true != 0)][:20]:
        violations.append(f"deceased count {true[idx]:g} published as a number: {df.loc[idx].to_dict()}")

    is_range = marker == DECEASED_RANGE_MARKER
    low, high = df[DECEASED_LOW_COL].astype(float), df[DECEASED_HIGH_COL].astype(float)
    exp_low, exp_high = deceased_band(true.to_numpy(dtype=float))
    bad = is_range & ((low != exp_low) | (high != exp_high))
    for idx in df.index[bad][:20]:
        violations.append(f"deceased band [{low[idx]}, {high[idx]}] is not the band of true count {true[idx]:g}: {df.loc[idx].to_dict()}")

    keys = [period_col, "population_segment", "dimension", "category"]
    comb_marker, _, _ = _combined_high(flow_df, keys, df, combined_flow_type, "count")
    comb_hidden = pd.notna(comb_marker) & (comb_marker != PRIMARY_SUPPRESSION_MARKER)
    for idx in df.index[is_range.to_numpy() & comb_hidden][:20]:
        violations.append(f"deceased band published next to a hidden inactive cell: {df.loc[idx].to_dict()}")

    rels = _deceased_relationships(df, period_col)
    for p, r in _pinned_deceased(df, rels)[:20]:
        violations.append(f"deceased band can be pinned from published numbers via {rels[r][2]}'s categories: {df.iloc[p].to_dict()}")
    return violations
