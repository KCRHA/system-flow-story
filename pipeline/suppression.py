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
from itertools import combinations

import pandas as pd

from .config import PRIMARY_SUPPRESSION_MARKER, SECONDARY_SUPPRESSION_MARKER, SUPPRESSION_THRESHOLD

TRUE_COUNT_COL = "_true_count"  # internal only — never written to exported JSON
# Distinct from PRIMARY_SUPPRESSION_MARKER/SECONDARY_SUPPRESSION_MARKER (a
# single small cell) — this means "this whole demographic slice can't be
# safely shown," which the frontend renders as its own message rather than
# folding it into a normal per-cell "*"/"**" display.
INSUFFICIENT_POPULATION_MARKER = "insufficient_population"


def apply_full_suppression_pipeline(df: pd.DataFrame, group_cols: list[str], count_col: str = "count") -> pd.DataFrame:
    df = df.copy()
    df[TRUE_COUNT_COL] = df[count_col]
    df["suppression_marker"] = None
    # > 0: a true zero is never suppressed — it can't identify a person.
    df.loc[(df[TRUE_COUNT_COL] > 0) & (df[TRUE_COUNT_COL] < SUPPRESSION_THRESHOLD), "suppression_marker"] = PRIMARY_SUPPRESSION_MARKER

    if "dimension" in df.columns:
        eligible = df[df["dimension"] != "overall"]
    else:
        eligible = df

    for _, group in eligible.groupby(group_cols, dropna=False):
        primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
        if _needs_secondary(primary[TRUE_COUNT_COL]):
            _pick_secondary(df, group, count_col)

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


def _pick_secondary(df: pd.DataFrame, group: pd.DataFrame, count_col: str) -> None:
    """Shared by apply_full_suppression_pipeline and
    apply_crosstab_secondary_suppression: given a group that
    _needs_secondary(...), marks one more visible cell in it, mutating
    `df` in place. No-op if the group has nothing left to hide (already
    fully suppressed some other way)."""
    visible = group[group["suppression_marker"].isna()].dropna(subset=[TRUE_COUNT_COL])
    if visible.empty:
        return
    # Prefer hiding a nonzero cell — a hidden zero protects the primary
    # cell just as well arithmetically, but there's no privacy reason to
    # ever hide a true zero, so it's only picked as a last resort (every
    # other visible category already spoken for).
    nonzero_visible = visible[visible[TRUE_COUNT_COL] > 0]
    candidates = nonzero_visible if not nonzero_visible.empty else visible
    next_smallest_idx = candidates[TRUE_COUNT_COL].idxmin()
    df.loc[next_smallest_idx, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER


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
    "deceased," which tends to be the smallest value in many rows at
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


def apply_race_crossdim_suppression(
    df: pd.DataFrame, group_cols: list[str], race_dimensions: list[str], count_col: str = "count"
) -> pd.DataFrame:
    """Run AFTER apply_full_suppression_pipeline (and, for tables that have
    it, apply_crosstab_secondary_suppression), BEFORE
    apply_insufficient_population_fallback/validate*, on the same df.

    The race_* dimensions are deliberately NOT mutually exclusive (see
    config.py's RACE_DIMENSIONS comment) — a person can be "Included" in
    more than one at once. Each dimension is still its own clean partition
    on its own (Included + Not Included = the scope's "overall" total), so
    apply_full_suppression_pipeline's within-dimension protection is sound
    on its own terms. But that overlap opens a *cross*-dimension gap it
    can never see: two individually-visible, above-threshold "Included"
    counts from two different race dimensions, plus the scope's own
    published "overall" total, let a reader lower-bound the population
    Included in BOTH at once via inclusion-exclusion
    (count_A + count_B - total) — a number nobody decided to publish,
    which can land under SUPPRESSION_THRESHOLD even though every
    contributing cell looks safe in isolation.

    `group_cols` is exactly what was passed to apply_full_suppression_pipeline
    for this table — its own "dimension" column is stripped internally to
    get the shared scope (e.g. ["month", "population_segment", "flow_type"])
    that race dimensions are compared within. `race_dimensions` is
    config.py's RACE_DIMENSIONS, passed explicitly rather than imported
    here to keep this module free of domain-specific dimension lists.

    Only the two-dimension "both Included" bound above is checked —
    per-conversation scope, same as apply_crosstab_secondary_suppression's
    own docstring; other inclusion-exclusion combinations (three-or-more
    dimensions, or the "Not Included" / complement side) are a separate
    follow-up, not covered here.

    Suppressing just the "Included" cell of a violating dimension would
    accomplish nothing — its own "Not Included" sibling plus the scope's
    known overall total would immediately hand the hidden value right
    back — so both categories of a chosen dimension are suppressed
    together, closing that dimension's breakdown for that scope entirely.
    Picks greedily (most-violated dimension first, same most-constrained-
    first spirit as _resolve_crosstab_period) until no violating pair
    remains in the scope.
    """
    df = df.copy()
    scope_cols = [c for c in group_cols if c != "dimension"]
    race_set = set(race_dimensions)

    overall = df[(df["dimension"] == "overall") & df["suppression_marker"].isna()]
    overall_totals = {key: group[TRUE_COUNT_COL].iloc[0] for key, group in overall.groupby(scope_cols, dropna=False)}

    race_rows = df[df["dimension"].isin(race_set)]
    for key, scope_group in race_rows.groupby(scope_cols, dropna=False):
        total = overall_totals.get(key)
        if total is None:
            continue

        dim_index = {dim: g.index for dim, g in scope_group.groupby("dimension")}
        visible = scope_group[(scope_group["category"] == "Included") & scope_group["suppression_marker"].isna()]
        visible_included = dict(zip(visible["dimension"], visible[TRUE_COUNT_COL]))

        while True:
            degree = {dim: 0 for dim in visible_included}
            for a, b in combinations(visible_included, 2):
                bound = visible_included[a] + visible_included[b] - total
                if 1 <= bound < SUPPRESSION_THRESHOLD:
                    degree[a] += 1
                    degree[b] += 1
            violating = {dim: n for dim, n in degree.items() if n > 0}
            if not violating:
                break
            max_degree = max(violating.values())
            # Tie-break on smallest true count, then name, purely for a
            # deterministic pick among equally-violated dimensions — no
            # privacy reasoning behind the order itself.
            pick = min((dim for dim in violating if violating[dim] == max_degree), key=lambda d: (visible_included[d], d))
            df.loc[dim_index[pick], "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER
            del visible_included[pick]

    df.loc[df["suppression_marker"].notna(), count_col] = pd.NA
    return df


def apply_insufficient_population_fallback(
    df: pd.DataFrame,
    period_col: str,
    main_group_cols: list[str],
    crosstab_group_cols: list[str],
    count_col: str = "count",
) -> pd.DataFrame:
    """Run AFTER apply_full_suppression_pipeline and (if the table has
    indiv_flow_* rows) apply_crosstab_secondary_suppression, on the same
    df. `main_group_cols`/`crosstab_group_cols` are exactly the group_cols
    you're about to pass to validate()/validate_crosstab() — this reuses
    the identical grouping so it resolves precisely what those would
    otherwise flag.

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
    that row/column's own published total flow_type (e.g. indiv_deceased
    for an outflow_bucket="deceased" column, indiv_newly_homeless for an
    inflow_bucket="newly_homeless" row) — a visible total is exactly what
    would make the hidden cells in that row/column arithmetically
    recoverable, so closing it off is what actually resolves the
    vulnerability. Every OTHER flow_type for that same (dimension,
    category) — active_total, experienced_homelessness, an unrelated
    row/column's own cells, etc. — has nothing to do with this specific
    row/column and is left alone: a large, well-populated category (e.g.
    a common race) can easily have one narrow, naturally-small crosstab
    slice (like a specific inflow reason crossed with "Deceased") without
    the category's other, unrelated numbers needing to go dark too.
    """
    df = df.copy()
    if "dimension" not in df.columns or "category" not in df.columns:
        return df
    has_flow_type = "flow_type" in df.columns

    def _protected(marker_series: pd.Series) -> bool:
        return marker_series.isin([SECONDARY_SUPPRESSION_MARKER, INSUFFICIENT_POPULATION_MARKER]).any()

    def _key(period, segment, dimension, category, flow_type=None):
        # length/return-cohort tables have no flow_type column at all
        # (each row already IS one specific measurement) — every other
        # table's blank_keys carry the specific flow_type so blanking
        # stays scoped to it, not every flow_type sharing the same
        # (dimension, category).
        return (period, segment, dimension, category, flow_type) if has_flow_type else (period, segment, dimension, category)

    blank_keys: set[tuple] = set()

    eligible = df[df["dimension"] != "overall"]
    for key, group in eligible.groupby(main_group_cols, dropna=False):
        primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
        if _needs_secondary(primary[TRUE_COUNT_COL]) and not _protected(group["suppression_marker"]):
            key_dict = dict(zip(main_group_cols, key if isinstance(key, tuple) else (key,)))
            flow_type = key_dict.get("flow_type")
            for category in primary["category"]:
                blank_keys.add(_key(key_dict[period_col], key_dict["population_segment"], key_dict["dimension"], category, flow_type))

    if "inflow_bucket" in df.columns:
        is_pair = df["inflow_bucket"].notna()
        for axis_col in ("inflow_bucket", "outflow_bucket"):
            for key, group in df[is_pair].groupby([*crosstab_group_cols, axis_col], dropna=False):
                primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
                if _needs_secondary(primary[TRUE_COUNT_COL]) and not _protected(group["suppression_marker"]):
                    key_dict = dict(zip([*crosstab_group_cols, axis_col], key if isinstance(key, tuple) else (key,)))
                    period = key_dict[period_col]
                    segment = key_dict["population_segment"]
                    dimension = key_dict["dimension"]
                    category = key_dict["category"]
                    for flow_type in group["flow_type"].unique():
                        blank_keys.add(_key(period, segment, dimension, category, flow_type))
                    blank_keys.add(_key(period, segment, dimension, category, f"indiv_{key_dict[axis_col]}"))

    if not blank_keys:
        return df

    key_cols = [period_col, "population_segment", "dimension", "category"] + (["flow_type"] if has_flow_type else [])
    blank_df = pd.DataFrame(list(blank_keys), columns=key_cols)
    blank_df["_blank"] = True
    merged = df.merge(blank_df, on=key_cols, how="left")
    mask = merged["_blank"].fillna(False).to_numpy()
    df.loc[mask, "suppression_marker"] = INSUFFICIENT_POPULATION_MARKER
    df.loc[mask, count_col] = pd.NA
    return df


def validate_crosstab(df: pd.DataFrame, group_cols: list[str]) -> list[str]:
    """Companion to apply_crosstab_secondary_suppression — same hard-gate
    contract as validate(). Call alongside it, not instead of it (this
    only checks the row/column groups, not the general suppression
    invariants validate() already covers)."""
    if "inflow_bucket" not in df.columns:
        return []
    violations = []
    is_pair = df["inflow_bucket"].notna()
    for axis_col in ("inflow_bucket", "outflow_bucket"):
        for key, group in df[is_pair].groupby([*group_cols, axis_col], dropna=False):
            primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
            # Counts INSUFFICIENT_POPULATION_MARKER as protection too, not
            # just the literal "**" — apply_insufficient_population_fallback
            # can repurpose a cell that was already this group's valid
            # secondary pick into a whole-scope blank; it's still just as
            # hidden either way, so it still satisfies the group's need.
            has_secondary = group["suppression_marker"].isin([SECONDARY_SUPPRESSION_MARKER, INSUFFICIENT_POPULATION_MARKER]).any()
            if _needs_secondary(primary[TRUE_COUNT_COL]) and not has_secondary:
                key_dict = dict(zip([*group_cols, axis_col], key if isinstance(key, tuple) else (key,)))
                violations.append(f"crosstab group {key_dict} needs secondary suppression but has none")
    return violations


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
    for key, group in eligible.groupby(group_cols, dropna=False):
        primary = group[group["suppression_marker"] == PRIMARY_SUPPRESSION_MARKER]
        # See validate_crosstab's identical comment — INSUFFICIENT_POPULATION_MARKER
        # counts as protection too, not just the literal "**".
        has_secondary = group["suppression_marker"].isin([SECONDARY_SUPPRESSION_MARKER, INSUFFICIENT_POPULATION_MARKER]).any()
        if _needs_secondary(primary[TRUE_COUNT_COL]) and not has_secondary:
            key_dict = dict(zip(group_cols, key if isinstance(key, tuple) else (key,)))
            violations.append(f"group {key_dict} needs secondary suppression (single suppressed cell, or multiple suppressed cells all equal to 1 or 10) but has none")

    return violations
