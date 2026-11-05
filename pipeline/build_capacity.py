"""Builds dashboard_capacity_monthly: one row per (month, project_type,
subregion), sourced from program_performance_metrics (TimePeriod = 'Month')
joined to program_attributes on ProgramID for the HUD ProjectTypeCode
rollup and the Subregion breakdown.

Units measure household capacity; beds measure individual-person capacity.
This dashboard's flow metrics (Tables 1/2) are about people, and for most
project types the unit-based fields are still the default measures here —
beds are kept only as a secondary reference figure. Emergency Shelter (the
"es" bucket) is the deliberate exception: ES programs serve individuals who
aren't necessarily part of a fixed household unit the way TH/RRH/PH
enrollments are, so its primary capacity figure is beds_in_system (not
units_in_system) and its utilization figure is bed_pct_utilization (built
from BedNightsUsedNumerator/BedNightsAvailableDenominator, not the
UnitNights equivalent) and its turnover figure is people_per_bed (not
households_per_unit). TH/RRH/PH keep the unit/household basis unchanged.
Both bases are computed for every project type regardless (the inputs cost
nothing extra to aggregate) — CapacitySection.jsx picks which pair of
fields to read per project_type, see its own per-type field maps.

subregion is "Overall" for most rows (the whole system — same totals this
table always published before the subregion breakdown existed), plus one
additional row per (period, project_type) for each of the 6 King County
subregions in config.py's SUBREGION_DISPLAY_LABELS — see that constant's
own comment for why Capacity, which has no per-person dimension at all,
still gets scoped by subregion (a program-location fact, not a person one)
when the frontend's two person-level subregion filters are active.

Each scope's ratio columns (throughput_hh_per_unit, pct_utilization,
households_per_unit, pct_exited) are computed fresh within that scope, NOT
derived by summing/averaging the "Overall" row's own ratios afterward — a
ratio-of-sums isn't a sum-of-ratios, so every scope needs its own
numerator/denominator pass (see _grouped_rate_metrics/_grouped_yearly_metrics).

enrolled/exited/active (household headcounts — people, not inventory) are
small-cell-suppressed by export.py, same reasoning and the same
suppression.py primitives as every person-level table: the subregion
breakdown above turns what used to be one large system-wide number per
(period, project_type) into 7 (the "Overall" scope plus 6 named
subregions), and a sparsely-served subregion/project_type combination can
land a household count as low as 1 — see export.py's
_suppress_capacity_household_count. units_in_system/beds_in_system (bed and
unit inventory) and pct_utilization (unit-night inventory utilization) are
never suppressed — they describe physical capacity, not people, so a small
value there doesn't identify anyone. throughput_hh_per_unit/
households_per_unit/pct_exited are derived FROM a household count, so
export.py nulls them alongside whichever headcount they're built from
(enrolled/active/active+exited respectively) rather than leaving a ratio
that would just hand the suppressed headcount back via the room/unit count
published right next to it.
"""
import pandas as pd

from .config import CAPACITY_PROJECT_TYPE_GROUPS, SUBREGION_DISPLAY_LABELS

OVERALL_SUBREGION = "Overall"


def _project_type_bucket(hud_code) -> str | None:
    for bucket, codes in CAPACITY_PROJECT_TYPE_GROUPS.items():
        if hud_code in codes:
            return bucket
    return None


def _with_subregion_scopes(joined: pd.DataFrame, group_cols: list[str], metrics_fn) -> pd.DataFrame:
    """Runs `metrics_fn` (one of the two per-table aggregation functions
    below) twice: once over all of `joined` (every in-scope program,
    regardless of subregion — the "Overall" scope), and once restricted to
    rows whose Subregion maps to one of SUBREGION_DISPLAY_LABELS' 6 named
    King County subregions, grouped by subregion as an extra key. Returns
    both concatenated, with "subregion" always a column — OVERALL_SUBREGION
    on the first set, a real subregion name on the second."""
    overall = metrics_fn(joined, group_cols)
    overall["subregion"] = OVERALL_SUBREGION

    by_subregion = joined.copy()
    by_subregion["subregion"] = by_subregion["Subregion"].map(SUBREGION_DISPLAY_LABELS)
    by_subregion = by_subregion.dropna(subset=["subregion"])
    by_subregion = metrics_fn(by_subregion, [*group_cols, "subregion"])

    return pd.concat([overall, by_subregion], ignore_index=True)


def _grouped_rate_metrics(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = df.groupby(group_cols).agg(
        units_in_system=("MaxUnitsAvailableDuringTimeframe", "sum"),
        enrolled=("EnrolledDuringTimeframe", "sum"),
        unit_nights_used=("UnitNightsUsedNumerator", "sum"),
        unit_nights_available=("UnitNightsAvailableDenominator", "sum"),
        beds_in_system=("MaxBedsAvailableDuringTimeframe", "sum"),
        bed_nights_used=("BedNightsUsedNumerator", "sum"),
        bed_nights_available=("BedNightsAvailableDenominator", "sum"),
    ).reset_index()
    grouped["throughput_hh_per_unit"] = grouped["enrolled"] / grouped["units_in_system"]
    grouped["pct_utilization"] = grouped["unit_nights_used"] / grouped["unit_nights_available"]
    # Emergency Shelter's own utilization figure — see module docstring —
    # same unit-nights-used/available ratio shape, just the bed-nights pair
    # of columns instead. Computed for every project type (not just "es"),
    # same reasoning as beds_in_system/units_in_system both always being
    # aggregated above; CapacitySection.jsx is what actually picks it.
    grouped["bed_pct_utilization"] = grouped["bed_nights_used"] / grouped["bed_nights_available"]
    return grouped


def _build_capacity_rows_for_period(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame, time_period: str, period_col: str, as_of: pd.Timestamp) -> pd.DataFrame:
    scoped = performance_metrics[performance_metrics["TimePeriod"] == time_period].copy()
    # The export window's own start/end cutoff is scoped by
    # TimePeriodStartDate at monthly granularity — a month's start is
    # also its own completion boundary, so that alone correctly excludes
    # the current in-progress month. It does NOT generalize to a longer
    # grain: a quarter/year "starting" within the safe window can still
    # extend past today (e.g. a quarter starting on the window's own end
    # cutoff is 3 months from complete). Filter on each row's own
    # TimePeriodEndDate instead, which is unambiguous at any grain.
    scoped = scoped[scoped["TimePeriodEndDate"] < as_of]

    joined = scoped.merge(
        program_attributes[["ProgramID", "ProjectTypeCode", "Subregion"]],
        on="ProgramID",
        how="left",
    )
    joined["project_type"] = joined["ProjectTypeCode"].apply(_project_type_bucket)
    joined = joined.dropna(subset=["project_type"])

    grouped = _with_subregion_scopes(joined, ["TimePeriodStartDate", "project_type"], _grouped_rate_metrics)
    grouped = grouped.rename(columns={"TimePeriodStartDate": period_col})

    # "enrolled" kept through to export.py (not dropped here) even though
    # it wasn't published before the subregion breakdown existed —
    # export.py's _suppress_capacity_household_count needs the raw
    # household count itself to suppress, not just the throughput_hh_per_unit
    # ratio derived from it. Published nulled-with-a-marker like every
    # other suppressed count in this pipeline, not hidden.
    return grouped[[period_col, "project_type", "subregion", "units_in_system", "enrolled", "throughput_hh_per_unit", "pct_utilization", "beds_in_system", "bed_pct_utilization"]]


def build_capacity_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    return _build_capacity_rows_for_period(performance_metrics, program_attributes, "Month", "month", as_of)


def build_capacity_quarterly_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per (quarter, project_type, subregion) — for the Utilization chart's
    quarterly trend. Unlike dashboard_capacity_yearly's Enrolled/Exited
    (monthly snapshots that would double-count if summed), UnitNightsUsed/
    Available are per-night counts with no such risk either way — using
    the source table's own native 'Quarter' rows here anyway, for
    consistency with the rest of this module rather than summing 'Month'
    rows ourselves.
    """
    return _build_capacity_rows_for_period(performance_metrics, program_attributes, "Quarter", "quarter", as_of)


def _grouped_yearly_metrics(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = df.groupby(group_cols).agg(
        units_in_system=("MaxUnitsAvailableDuringTimeframe", "sum"),
        beds_in_system=("MaxBedsAvailableDuringTimeframe", "sum"),
        enrolled=("EnrolledDuringTimeframe", "sum"),
        exited=("ExitedDuringTimeframe", "sum"),
        active=("ActiveEnrollmentsInTimeframe", "sum"),
    ).reset_index()

    # Both metrics below are built on `active` (ActiveEnrollmentsInTimeframe:
    # everyone touched by the project at any point in the year), not
    # `enrolled` (EnrolledDuringTimeframe) — confirmed directly against
    # the source data that active == exited + ActiveAtEndOfTimeframe
    # (holds for 5369/5372 program-years checked), i.e. it's the true
    # "active at any point" headcount, while `enrolled` runs lower and let
    # pct_exited exceed 100% for some project-type/years, which isn't
    # meaningful — you can't have more exits than people who were ever
    # there to exit.

    # Households actually served per unit that year — e.g. one TH unit
    # with ~2-month average stays should show ~6 (12 months / 2).
    grouped["households_per_unit"] = (grouped["active"] / grouped["units_in_system"]).where(grouped["units_in_system"] > 0)
    # Emergency Shelter's own turnover figure — see module docstring — same
    # shape as households_per_unit above, just active/beds_in_system instead
    # of active/units_in_system. Computed for every project type, same
    # reasoning as bed_pct_utilization in _grouped_rate_metrics above.
    grouped["people_per_bed"] = (grouped["active"] / grouped["beds_in_system"]).where(grouped["beds_in_system"] > 0)
    # Of everyone active at any point in the year, what share exited
    # within that same year (vs. still active at year-end) — the
    # "turnover rate". Structurally bounded to [0, 1] since `active` is
    # exits plus everyone still active at year-end. where() (not a bare
    # division) so a zero-active year reads as "no data" (null), not a
    # fabricated 0%.
    grouped["pct_exited"] = (grouped["exited"] / grouped["active"]).where(grouped["active"] > 0)
    return grouped


def build_capacity_yearly_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame) -> pd.DataFrame:
    """One row per (year, project_type, subregion), for the Turnover chart's
    percent-exited and households-per-unit metrics.

    Sourced from program_performance_metrics's own TimePeriod='Year' rows
    — NOT derived by summing the 'Month' rows used above, because
    EnrolledDuringTimeframe/ExitedDuringTimeframe are monthly snapshots (a
    household enrolled across N months of one stay is counted again in
    each of those N months), so summing them would overcount relative to
    a true annual headcount. The source table's own Year-grain rows are
    already a correctly deduplicated once-per-household-per-year count —
    confirmed directly against a sample program's data (Enrolled and
    Exited both landed close to its real headcount, not a monthly-summed
    multiple of it).
    """
    yearly = performance_metrics[performance_metrics["TimePeriod"] == "Year"].copy()

    joined = yearly.merge(
        program_attributes[["ProgramID", "ProjectTypeCode", "Subregion"]],
        on="ProgramID",
        how="left",
    )
    joined["project_type"] = joined["ProjectTypeCode"].apply(_project_type_bucket)
    joined = joined.dropna(subset=["project_type"])

    grouped = _with_subregion_scopes(joined, ["TimePeriodStartDate", "project_type"], _grouped_yearly_metrics)
    grouped["year"] = grouped["TimePeriodStartDate"].apply(lambda d: pd.Timestamp(d).year)

    return grouped[["year", "project_type", "subregion", "enrolled", "exited", "active", "pct_exited", "units_in_system", "households_per_unit", "beds_in_system", "people_per_bed"]]
