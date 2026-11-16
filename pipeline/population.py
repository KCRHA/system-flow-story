"""Population-segment filters.

`filter_population` (episode-level: dashboard_flow_monthly's inflow/
outflow/active rows, dashboard_length_monthly, dashboard_return_cohorts).
Ported from BFZ_Monthly_Report_2026_04_03.ipynb's filter_population(),
trimmed to the segments this dashboard needs (the source notebook also
has a "Chronic Veteran" variant this dashboard doesn't use; its own
"Families" branch — `EpisodeMaxCountChildren/Adults >= 1` — was left out
in favor of the HouseholdType-based definition below, not because it's
wrong, just a different valid lever over the same underlying data). Single
Adults also departs from the source notebook's count-based branch and uses
EpisodeHouseholdType, for the same consistency with household type.
Requires `VeteranStatus` joined in from Client_Demographics on
PersonalID first — episode_systemwide itself has no veteran column.

The Senior branch reads EpisodeAgeTier directly — episode_systemwide
computes it as of the later of the episode's own start or each row's own
TimePeriodStartDate (Episode_Systemwide notebook, 2026-10 "month-by-month
age calculation" change), so it's already correct per month and doesn't
need a local recomputation.

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


def filter_population(df: pd.DataFrame, pop_label: str, month_start) -> pd.DataFrame:
    if pop_label == "Single Adults":
        # EpisodeHouseholdType, same field as Family below, so this segment
        # matches the household_type_adults_only dimension. Replaced
        # `EpisodeMaxCountChildren.fillna(0) == 0` (2026-11-16): that
        # counted blank child counts as zero, pulling in episodes with no
        # known household type, and diverged from Adults Only whenever an
        # episode's most common type was adults-only but one event had a child.
        return df[df["EpisodeHouseholdType"] == "Household without Children"]
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
        pop_df = df[yya_flag].copy()
        # FlagYYA and EpisodeAgeTier can disagree for someone right at a
        # month-boundary 12th/25th birthday: FlagYYA's own floor/ceiling
        # check is "12-24 at any point in the month" (floor checked as of
        # month-end), while EpisodeAgeTier uses a single reference point
        # (the later of the episode's own start or the month's start) — see
        # module docstring. FlagYYA is the authoritative per-member YYA
        # signal, so clamp these adjacent-tier disagreements back into the
        # range it already asserts, rather than letting a handful of
        # genuinely-YYA people leak into "0 to 11"/"25 to 34" in the
        # age_category breakdown with no visible "YYA member outside
        # 12-24" row to explain where they went.
        pop_df.loc[pop_df["EpisodeAgeTier"] == "0 to 11", "EpisodeAgeTier"] = "12 to 17"
        pop_df.loc[pop_df["EpisodeAgeTier"] == "25 to 34", "EpisodeAgeTier"] = "18 to 24"
        return pop_df
    if pop_label == "Senior":
        # Age-tier membership check — unlike YYA, Seniors isn't scoped to
        # heads of household, and there's no "aging out" of being a senior
        # to account for.
        return df[df["EpisodeAgeTier"].isin(["55 to 64", "65 or Above"])]
    return df  # "All"
