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
"""
import pandas as pd

from .config import PRIMARY_SUPPRESSION_MARKER, SECONDARY_SUPPRESSION_MARKER, SUPPRESSION_THRESHOLD

TRUE_COUNT_COL = "_true_count"  # internal only — never written to exported JSON


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
        if not _needs_secondary(primary[TRUE_COUNT_COL]):
            continue

        visible = group[group["suppression_marker"].isna()].dropna(subset=[TRUE_COUNT_COL])
        if visible.empty:
            continue
        # Prefer hiding a nonzero cell — a hidden zero protects the primary
        # cell just as well arithmetically, but there's no privacy reason to
        # ever hide a true zero, so it's only picked as a last resort (every
        # other visible category already spoken for).
        nonzero_visible = visible[visible[TRUE_COUNT_COL] > 0]
        candidates = nonzero_visible if not nonzero_visible.empty else visible
        next_smallest_idx = candidates[TRUE_COUNT_COL].idxmin()
        df.loc[next_smallest_idx, "suppression_marker"] = SECONDARY_SUPPRESSION_MARKER

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
        has_secondary = (group["suppression_marker"] == SECONDARY_SUPPRESSION_MARKER).any()
        if _needs_secondary(primary[TRUE_COUNT_COL]) and not has_secondary:
            key_dict = dict(zip(group_cols, key if isinstance(key, tuple) else (key,)))
            violations.append(f"group {key_dict} needs secondary suppression (single suppressed cell, or multiple suppressed cells all equal to 1 or 10) but has none")

    return violations
