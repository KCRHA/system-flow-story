"""Population-segment filters.

Two variants, because episode_systemwide and All_Program_Enrollments carry
different columns for the same underlying concepts:

- `filter_population` (episode-level: dashboard_flow_monthly's inflow/
  outflow/active rows, dashboard_length_monthly, dashboard_return_cohorts).
  Ported from BFZ_Monthly_Report_2026_04_03.ipynb's filter_population(),
  trimmed to the five segments this dashboard needs (the source notebook
  also has "Families" and "Chronic Veteran" variants this dashboard doesn't
  use). Requires `VeteranStatus` joined in from Client_Demographics on
  PersonalID first — episode_systemwide itself has no veteran column.

- `filter_population_enrollment` (enrollment-level: the resource_* flow
  types in dashboard_flow_monthly, sourced from All_Program_Enrollments,
  which already computes its own household-level YYA/chronic fields
  directly — confirmed against All_Program_Enrollments_2026_01_22.ipynb's
  final columns_to_select). Also requires VeteranStatus joined in from
  Client_Demographics on PersonalID.
"""
import pandas as pd


def filter_population(df: pd.DataFrame, pop_label: str, month_start) -> pd.DataFrame:
    if pop_label == "Single Adults":
        return df[df["EpisodeMaxCountChildren"].fillna(0) == 0]
    if pop_label == "Chronic":
        return df[df["EpisodeChronicStatus"] == "Yes"]
    if pop_label == "Veteran":
        return df[df["VeteranStatus"] == "Yes"]
    if pop_label == "Youth and Young Adults":
        # AgedOutOfYYA arrives as whatever raw type the SQL driver returned
        # (pyodbc doesn't guarantee pandas Timestamp) — coerce both sides
        # explicitly rather than relying on the caller having already
        # normalized every column that might end up compared here.
        aged_out_of_yya = pd.to_datetime(df["AgedOutOfYYA"], errors="coerce")
        month_ts = pd.Timestamp(month_start)
        aged_out_before = aged_out_of_yya.notna() & (aged_out_of_yya < month_ts)
        yya_flag = (df["FlagYYA"] == 1) & ~aged_out_before
        age_tier = (df["EpisodeAgeTier"] == "18 to 24") | (
            (df["EpisodeAgeTier"] == "Under 18") & (df["FlagHeadOfHousehold"] == 1)
        )
        return df[yya_flag & age_tier]
    return df  # "All"


def filter_population_enrollment(df: pd.DataFrame, pop_label: str) -> pd.DataFrame:
    if pop_label == "Single Adults":
        return df[df["CountChildren"].fillna(0) == 0]
    if pop_label == "Chronic":
        return df[df["IndividualChronicallyHomelessAtEnrollmentStart"] == "Yes"]
    if pop_label == "Veteran":
        return df[df["VeteranStatus"] == "Yes"]
    if pop_label == "Youth and Young Adults":
        return df[df["YYA"] == "Yes"]
    return df  # "All"
