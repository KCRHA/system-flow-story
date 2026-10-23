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
  which already computes its own per-member YYA/chronic fields directly —
  confirmed against All_Program_Enrollments_2026_01_22.ipynb's final
  columns_to_select). Also requires VeteranStatus joined in from
  Client_Demographics on PersonalID.

Both Senior branches compute age fresh via age.age_tier_as_of_period()
instead of reading the raw EpisodeAgeTier/AgeTierAtEnrollment columns —
see age.py's module docstring for why those columns can't be trusted on
their own (frozen at episode/enrollment start, never recalculated).
Requires BirthDate joined onto `df` first (export.py, from Looker — see
age.py).

YYA follows the HUD youth-household definition (DataHubDevelopment PR #290,
2026-10): FlagYYA/YYA is now a per-member, per-month string computed
upstream straight from birthdates — "Non-YYA" (not in a youth household),
"YYA" (this member is themselves 12-24 in a youth household — no member of
the household is known to be 25+), or "YYA Household Member" (this member
is a non-youth member — age 0-11 or unknown — of an otherwise-youth
household). This dashboard's YYA population segment is just the "YYA"
value: individuals who are themselves the youth, per HUD's definition.
Before PR #290, both of these flags were household-level Yes/No (same
value for every member regardless of their own age), which is why this
module used to pair the flag with a separately-recomputed age-tier/
head-of-household check to approximate "is this particular row's own
person the youth". That workaround is gone now that the upstream flag is
already individual-level and age-precise every month.
"""
import pandas as pd

from .age import age_tier_as_of_period


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
        # AgedOutOfYYA arrives as whatever raw type the SQL driver returned
        # (pyodbc doesn't guarantee pandas Timestamp) — coerce explicitly.
        # FlagYYA itself is a string ("Non-YYA"/"YYA"/"YYA Household
        # Member" — see module docstring) and needs no coercion.
        #
        # AgedOutOfYYA is redundant with FlagYYA == "YYA" in principle (the
        # upstream per-month computation already stops returning "YYA" once
        # someone is 25+ for the whole month — see PR #290), but kept as a
        # defense-in-depth check consistent with build_flow.py's own
        # AgedOutOfYYA-based "aged out" outflow detection, which reads this
        # same column directly.
        aged_out_of_yya = pd.to_datetime(df["AgedOutOfYYA"], errors="coerce")
        month_ts = pd.Timestamp(month_start)
        aged_out_before = aged_out_of_yya.notna() & (aged_out_of_yya < month_ts)
        yya_flag = (df["FlagYYA"] == "YYA") & ~aged_out_before
        return df[yya_flag]
    if pop_label == "Senior":
        # Age-tier membership check — unlike YYA, Seniors isn't scoped to
        # heads of household, and there's no "aging out" of being a senior
        # to account for.
        current_tier = age_tier_as_of_period(df["BirthDate"], pd.Timestamp(month_start), df["EpisodeStartDate"])
        return df[current_tier.isin(["55 to 64", "65 or Above"])]
    return df  # "All"


def filter_population_enrollment(df: pd.DataFrame, period_start, pop_label: str) -> pd.DataFrame:
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
        # YYA is per-member (see module docstring) — "YYA" means this
        # enrollment's own person is themselves 12-24 in a youth household,
        # not just that they belong to one.
        return df[df["YYA"] == "YYA"]
    if pop_label == "Senior":
        current_tier = age_tier_as_of_period(df["BirthDate"], pd.Timestamp(period_start), df["ProjectStartDate"])
        return df[current_tier.isin(["55 to 64", "65 or Above"])]
    return df  # "All"
