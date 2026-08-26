"""Builds dashboard_capacity_monthly: one row per (month, project_type),
sourced from program_performance_metrics (TimePeriod = 'Month') joined to
program_attributes on ProgramID for the HUD ProjectTypeCode rollup.

Units measure household capacity; beds measure individual-person capacity.
This dashboard's flow metrics (Tables 1/2) are about households, so the
unit-based fields are the default measures — beds are kept only as a
secondary reference figure.
"""
import pandas as pd

from .config import CAPACITY_PROJECT_TYPE_GROUPS


def _project_type_bucket(hud_code) -> str | None:
    for bucket, codes in CAPACITY_PROJECT_TYPE_GROUPS.items():
        if hud_code in codes:
            return bucket
    return None


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
        program_attributes[["ProgramID", "ProjectTypeCode"]],
        on="ProgramID",
        how="left",
    )
    joined["project_type"] = joined["ProjectTypeCode"].apply(_project_type_bucket)
    joined = joined.dropna(subset=["project_type"])

    grouped = joined.groupby(["TimePeriodStartDate", "project_type"]).agg(
        units_in_system=("MaxUnitsAvailableDuringTimeframe", "sum"),
        enrolled=("EnrolledDuringTimeframe", "sum"),
        unit_nights_used=("UnitNightsUsedNumerator", "sum"),
        unit_nights_available=("UnitNightsAvailableDenominator", "sum"),
        beds_in_system=("MaxBedsAvailableDuringTimeframe", "sum"),
    ).reset_index()

    grouped["throughput_hh_per_unit"] = grouped["enrolled"] / grouped["units_in_system"]
    grouped["pct_utilization"] = grouped["unit_nights_used"] / grouped["unit_nights_available"]
    grouped = grouped.rename(columns={"TimePeriodStartDate": period_col})

    return grouped[[period_col, "project_type", "units_in_system", "throughput_hh_per_unit", "pct_utilization", "beds_in_system"]]


def build_capacity_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    return _build_capacity_rows_for_period(performance_metrics, program_attributes, "Month", "month", as_of)


def build_capacity_quarterly_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per (quarter, project_type) — for the Utilization chart's
    quarterly trend. Unlike dashboard_capacity_yearly's Enrolled/Exited
    (monthly snapshots that would double-count if summed), UnitNightsUsed/
    Available are per-night counts with no such risk either way — using
    the source table's own native 'Quarter' rows here anyway, for
    consistency with the rest of this module rather than summing 'Month'
    rows ourselves.
    """
    return _build_capacity_rows_for_period(performance_metrics, program_attributes, "Quarter", "quarter", as_of)


def build_capacity_yearly_rows(performance_metrics: pd.DataFrame, program_attributes: pd.DataFrame) -> pd.DataFrame:
    """One row per (year, project_type), for the Turnover chart's percent-
    exited and households-per-unit metrics.

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
        program_attributes[["ProgramID", "ProjectTypeCode"]],
        on="ProgramID",
        how="left",
    )
    joined["project_type"] = joined["ProjectTypeCode"].apply(_project_type_bucket)
    joined = joined.dropna(subset=["project_type"])

    grouped = joined.groupby(["TimePeriodStartDate", "project_type"]).agg(
        units_in_system=("MaxUnitsAvailableDuringTimeframe", "sum"),
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

    # Households actually served per unit that year — e.g. one ES unit
    # with ~2-month average stays should show ~6 (12 months / 2).
    grouped["households_per_unit"] = (grouped["active"] / grouped["units_in_system"]).where(grouped["units_in_system"] > 0)
    # Of everyone active at any point in the year, what share exited
    # within that same year (vs. still active at year-end) — the
    # "turnover rate". Structurally bounded to [0, 1] since `active` is
    # exits plus everyone still active at year-end. where() (not a bare
    # division) so a zero-active year reads as "no data" (null), not a
    # fabricated 0%.
    grouped["pct_exited"] = (grouped["exited"] / grouped["active"]).where(grouped["active"] > 0)
    grouped["year"] = grouped["TimePeriodStartDate"].apply(lambda d: pd.Timestamp(d).year)

    return grouped[["year", "project_type", "enrolled", "exited", "active", "pct_exited", "units_in_system", "households_per_unit"]]
