"""Age-tier computation, reporting-period-relative.

episode_systemwide's EpisodeAgeTier and All_Program_Enrollments'
AgeTierAtEnrollment are each computed ONCE, at episode/enrollment start, by
the source notebooks' own age_helpers cell (see Episode_Systemwide/
All_Program_Enrollments) — then never recalculated. A long-open episode (or
enrollment) still reports whatever tier the person was at its start, even
years later, even after they've aged into a different tier through a
separate, newer episode. Population-segment membership (filter_population's
Senior/YYA branches) is checked across every one of a person's episodes in
the period (an OR), so someone can qualify as a Senior via a newer episode
while their longest-running episode's own frozen tier still reads well
below 55 — exactly the mismatch that produced a real, nonzero "45 to 54"
cell inside the Seniors segment's age_category breakdown and triggered
secondary suppression on "65 or Above" (see suppression.py).

This module recomputes age tier fresh instead of trusting that frozen
column: age as of the LATER of the reporting period's start or the
episode's/enrollment's own start date — the same convention HUD's own
Standard Reporting Terminology Glossary uses ("Age is calculated as of the
later of project start date or report start date"). A long-open episode's
tier now correctly advances as the report period itself advances, instead
of staying frozen at whatever the person was when the episode began.

Requires BirthDate, which neither episode_systemwide nor All_Program_
Enrollments/client_demographic actually carries — both source notebooks
drop it before publishing to Synapse (Client_Demographics.ipynb and
Episode_Systemwide's own age_helpers cell each do `.drop(columns=
["BirthDate", ...])`). export.py pulls it straight from Looker's
client_model view instead (client_model.birth_date), via connection.py's
query_looker().

age_in_years()/age_tier() are copied from the source notebooks' own
age_helpers cell (same tier vocabulary, same invalid-age handling) so a
"45 to 54"/"65 or Above" computed here means the same thing as one read
from EpisodeAgeTier elsewhere in this pipeline — only the reference date
differs.
"""
import numpy as np
import pandas as pd

from .config import DIMENSION_COLUMNS

MIN_VALID_AGE = 0
MAX_VALID_AGE = 110


def age_in_years(birth_date, as_of) -> pd.Series:
    """Whole years between birth_date and as_of (both Series). NaN where
    either is missing or the resulting age falls outside
    [MIN_VALID_AGE, MAX_VALID_AGE)."""
    birth = pd.to_datetime(birth_date, errors="coerce")
    as_of = pd.to_datetime(as_of, errors="coerce")

    years = as_of.dt.year - birth.dt.year
    before_birthday = (as_of.dt.month < birth.dt.month) | (
        (as_of.dt.month == birth.dt.month) & (as_of.dt.day < birth.dt.day)
    )
    age = (years - before_birthday.astype(int)).astype(float)
    return age.mask((age < MIN_VALID_AGE) | (age >= MAX_VALID_AGE))


def age_tier(age) -> pd.Series:
    """Map ages (in whole years) to the same tier labels as episode_systemwide's
    own EpisodeAgeTier/AgeTierAtEnrollment ("Unknown" for missing/invalid)."""
    age = pd.to_numeric(age, errors="coerce").astype(float)
    valid = (age >= MIN_VALID_AGE) & (age < MAX_VALID_AGE)
    conditions = [
        valid & (age < 12), valid & (age < 18), valid & (age < 25), valid & (age < 35),
        valid & (age < 45), valid & (age < 55), valid & (age < 65), valid,
    ]
    choices = [
        "0 to 11", "12 to 17", "18 to 24", "25 to 34",
        "35 to 44", "45 to 54", "55 to 64", "65 or Above",
    ]
    return pd.Series(np.select(conditions, choices, default="Unknown"), index=age.index)


def age_tier_as_of_period(birth_date, period_start, reference_start) -> pd.Series:
    """age_tier(), as of the LATER of the reporting period's own start
    (`period_start` — the month/quarter/year start the row's period is
    being built for; a single scalar timestamp in every call site today,
    broadcast across `reference_start`'s index) or the episode's/
    enrollment's own start (`reference_start` — EpisodeStartDate/
    ProjectStartDate, one per row).

    `period_start` wins once the period starts after the episode (the
    frozen-tier case this module exists to fix — see module docstring);
    `reference_start` wins for an episode that starts mid-period, so a
    brand-new episode's tier still reflects the person's age right as it
    begins rather than being pulled back to the period's own start.

    Takes the max via a 2-column frame, not a plain Series comparison —
    skips a missing side instead of propagating NaT when only one of
    `period_start`/`reference_start` is unset for a given row (reference_start
    missing is the realistic case: a bad/missing EpisodeStartDate; period_start
    is always a known value this pipeline itself constructs)."""
    reference_start = pd.to_datetime(reference_start, errors="coerce")
    if not isinstance(period_start, pd.Series):
        period_start = pd.Series(pd.Timestamp(period_start), index=reference_start.index)
    else:
        period_start = pd.to_datetime(period_start, errors="coerce")
    as_of = pd.concat([period_start, reference_start], axis=1).max(axis=1)
    return age_tier(age_in_years(birth_date, as_of))


def refresh_age_category(
    df: pd.DataFrame, period_start, start_col: str = "EpisodeStartDate", category_col: str | None = None
) -> pd.DataFrame:
    """Overwrites the age_category column (DIMENSION_COLUMNS["age_category"]
    == EpisodeAgeTier by default; pass category_col="AgeCategory" and
    start_col="ProjectStartDate" for the enrollment-level table instead)
    with age_tier_as_of_period() rather than whatever frozen, episode/
    enrollment-start-only value the source notebooks baked into that
    column (see this module's own docstring).

    Called once per (month/quarter/year) `period_start`, before anything
    downstream reads age_category — build_flow.py's _person_category_for_
    period's own read of this same column (for the indiv_*/indiv_flow_*
    partition) and every direct _count_by_category/_count_by_category_
    enrollment groupby on it (inflow/outflow/active_total/experienced_
    homelessness/resource_*, across build_flow.py/build_length.py/
    build_length_by_exit.py/build_return_cohorts.py) all pick up the
    corrected value for free, since each reads whatever this column
    currently holds rather than re-deriving it themselves.

    Requires `df` to already carry BirthDate (export.py's client_demographics
    merge) and `start_col` (always present — EpisodeStartDate/
    ProjectStartDate are core columns of their own source tables, not
    something this pipeline adds)."""
    category_col = category_col or DIMENSION_COLUMNS["age_category"]
    return df.assign(**{category_col: age_tier_as_of_period(df["BirthDate"], period_start, df[start_col])})
