"""Population-segment filters.

Two variants, because episode_systemwide and All_Program_Enrollments carry
different columns for the same underlying concepts:

- `filter_population` (episode-level: dashboard_flow_monthly's inflow/
  outflow/active rows, dashboard_length_monthly, dashboard_return_cohorts).
  Ported from BFZ_Monthly_Report_2026_04_03.ipynb's filter_population(),
  trimmed to the segments this dashboard needs (the source notebook also
  has a "Chronic Veteran" variant this dashboard doesn't use; its own
  "Families" branch — `EpisodeMaxCountChildren/Adults >= 1` — was left out
  in favor of the HouseholdType-based definition below, not because it's
  wrong, just a different valid lever over the same underlying data).
  Requires `VeteranStatus` joined in from Client_Demographics on
  PersonalID first — episode_systemwide itself has no veteran column.

- `filter_population_enrollment` (enrollment-level: the resource_* flow
  types in dashboard_flow_monthly, sourced from All_Program_Enrollments,
  which already computes its own household-level YYA/chronic fields
  directly — confirmed against All_Program_Enrollments_2026_01_22.ipynb's
  final columns_to_select). Also requires VeteranStatus joined in from
  Client_Demographics on PersonalID. Its YYA branch additionally restricts
  to the individual's own age tier (see below) — YYA itself is a
  household-level flag, so used alone it would also count non-HoH children
  who happen to belong to a YYA household.
"""
import pandas as pd


def filter_population(df: pd.DataFrame, pop_label: str, month_start) -> pd.DataFrame:
    if pop_label == "Single Adults":
        return df[df["EpisodeMaxCountChildren"].fillna(0) == 0]
    if pop_label == "Chronic":
        return df[df["EpisodeChronicStatus"] == "Yes"]
    if pop_label == "Veteran":
        return df[df["VeteranStatus"] == "Yes"]
    if pop_label == "Family":
        # EpisodeHouseholdType, not HouseholdCategory: HouseholdCategory
        # forces every household into exactly one bucket ("Family with
        # Children" beats "Youth and Young Adults" in its own priority
        # order — see All_Program_Enrollments_2026_01_22.ipynb), so a
        # household with both a young parent and a child would silently
        # disappear from the YYA segment if either segment were defined
        # from it. EpisodeHouseholdType has no such exclusivity — a
        # household can freely be both "Household with Children and
        # Adults" here and also match the Youth and Young Adults branch
        # below, same as any other pair of segments (e.g. chronic
        # veteran) is already free to overlap.
        return df[df["EpisodeHouseholdType"] == "Household with Children and Adults"]
    if pop_label == "Youth and Young Adults":
        # AgedOutOfYYA/FlagYYA/FlagHeadOfHousehold all arrive as whatever raw
        # type the SQL driver returned (pyodbc doesn't guarantee pandas
        # Timestamp/int64 — episode_systemwide's FlagYYA and
        # FlagHeadOfHousehold in particular come back as the strings "0"/"1",
        # not ints) — coerce explicitly rather than relying on the caller
        # having already normalized every column that might end up compared
        # here.
        aged_out_of_yya = pd.to_datetime(df["AgedOutOfYYA"], errors="coerce")
        month_ts = pd.Timestamp(month_start)
        aged_out_before = aged_out_of_yya.notna() & (aged_out_of_yya < month_ts)
        flag_yya = pd.to_numeric(df["FlagYYA"], errors="coerce")
        flag_hoh = pd.to_numeric(df["FlagHeadOfHousehold"], errors="coerce")
        yya_flag = (flag_yya == 1) & ~aged_out_before
        age_tier = (df["EpisodeAgeTier"] == "18 to 24") | (
            (df["EpisodeAgeTier"] == "Under 18") & (flag_hoh == 1)
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
    if pop_label == "Family":
        # Same reasoning as filter_population's Family branch: HouseholdType
        # (not HouseholdCategory), so this stays free to overlap with YYA
        # rather than losing shared households to whichever segment
        # HouseholdCategory's own priority order happens to favor.
        return df[df["HouseholdType"] == "Household with Children and Adults"]
    if pop_label == "Youth and Young Adults":
        # YYA alone is a household-level attribute — enrollments for a
        # non-HoH child in an otherwise-YYA household would satisfy it, so
        # apply the same individual-level age-tier restriction as
        # filter_population's episode-level YYA branch. Note
        # All_Program_Enrollments' age-tier column uses "0 to 17" for this
        # bucket where episode_systemwide's EpisodeAgeTier uses "Under 18" —
        # confirmed against the two tables' actual distinct values, not
        # assumed to match.
        age_tier = (df["AgeTierAtEnrollment"] == "18 to 24") | (
            (df["AgeTierAtEnrollment"] == "0 to 17") & (df["HeadOfHousehold"] == "Yes")
        )
        return df[(df["YYA"] == "Yes") & age_tier]
    return df  # "All"
