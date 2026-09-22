"""Demographic rollups derived from Client_Demographics columns.

GenderIdentity/GenderAlignment are computed here from GenderExpanded, not
the plain Gender column — Gender collapses any 2+ flag selection to a
generic "Multiple genders selected", with no detail on which flags
combined, while GenderExpanded (built from the same underlying 7-flag HMIS
gender multi-select in Client_Demographics.ipynb) preserves that detail: a
single label ("Man", "Woman", "Culturally Specific Identity",
"Transgender", "Non-Binary", "Questioning", "A Different Identity") for one
flag, two labels joined by " & " for exactly two flags, "Three or more
genders selected" for three or more, and "Unknown" for none (covers
DK/PNTA/Not Collected) — confirmed directly against that notebook's
Gender-override cell vs. its GenderExpanded-building cell, not assumed.
"""
import numpy as np
import pandas as pd

_UNKNOWN = "Unknown"
_THREE_PLUS = "Three or more genders selected"


def _selected_labels(gender_expanded: pd.Series) -> pd.Series:
    """GenderExpanded -> list of selected labels for a real 1- or 2-flag
    combo, or [] for the Unknown/3+ sentinels (which carry no per-flag
    detail to split on)."""

    def split(value):
        if value in (_UNKNOWN, _THREE_PLUS) or not isinstance(value, str):
            return []
        return value.split(" & ")

    return gender_expanded.apply(split)


def compute_gender_rollups(df: pd.DataFrame) -> pd.DataFrame:
    """Adds GenderIdentity (Male/Female/Non-binary or Other/Unknown) and
    GenderAlignment (Likely Cisgender/Likely Transgender/Unknown) columns,
    derived from `df["GenderExpanded"]`. Person-level — call once on
    Client_Demographics, not per merge.

    GenderIdentity: Man selected alone, or combined only with Different
    Identity / Questioning / Transgender, rolls up to Male (Woman
    symmetrically to Female) — Culturally Specific Identity, Non-Binary,
    and a Man+Woman selection are deliberately excluded from that "still
    counts" set and fall through to Non-binary or Other, same as every
    other unlisted combo and the 3+ sentinel.

    GenderAlignment: Man or Woman selected ALONE (and only alone) rolls up
    to Likely Cisgender; every other real selection (including Man/Woman
    combined with anything else) rolls up to Likely Transgender.
    """
    df = df.copy()
    gender_expanded = df["GenderExpanded"]
    is_unknown = gender_expanded == _UNKNOWN

    labels = _selected_labels(gender_expanded)
    has_man = labels.apply(lambda tokens: "Man" in tokens)
    has_woman = labels.apply(lambda tokens: "Woman" in tokens)
    has_csi = labels.apply(lambda tokens: "Culturally Specific Identity" in tokens)
    has_nb = labels.apply(lambda tokens: "Non-Binary" in tokens)

    is_male = has_man & ~has_woman & ~has_csi & ~has_nb
    is_female = has_woman & ~has_man & ~has_csi & ~has_nb

    df["GenderIdentity"] = np.select(
        [is_unknown, is_male, is_female],
        ["Unknown", "Male", "Female"],
        default="Non-binary or Other",
    )

    is_alone = gender_expanded.isin(["Man", "Woman"])
    df["GenderAlignment"] = np.select(
        [is_unknown, is_alone],
        ["Unknown", "Likely Cisgender"],
        default="Likely Transgender",
    )

    return df


_INCLUDED = "Included"
_NOT_INCLUDED = "Not Included"

# Raw boolean flags, straight from Client_Demographics (not a derived
# rollup like GenderExpanded — these are native columns, confirmed against
# Client_Demographics.ipynb's own RaceAndEthnicity/RaceAndEthnicityExpanded-
# building cell, which reads them the same way).
_RACE_FLAG_TO_COLUMN = {
    "AIAN": "RaceAndEthnicity_AIAN",
    "Asian": "RaceAndEthnicity_Asian",
    "Black": "RaceAndEthnicity_Black",
    "NHPI": "RaceAndEthnicity_NHPI",
    "White": "RaceAndEthnicity_WC",
    "HL": "RaceAndEthnicity_HL",
    "MENA": "RaceAndEthnicity_MENA",
}


def compute_race_rollups(df: pd.DataFrame) -> pd.DataFrame:
    """Adds 8 independent binary ("Included"/"Not Included") columns, one
    per race_* dimension in config.py:

    RaceIncludes_AIAN/_Asian/_Black/_NHPI/_White/_HL/_MENA — "Included" if
    that one specific RaceAndEthnicity_* flag is "Yes", regardless of what
    else is selected. This is the "alone or in combination with any other
    race/ethnicity" model — deliberately different from the plain
    RaceAndEthnicity column, which instead collapses any 2+ selection into
    one generic "Multiracial" bucket and so would silently exclude, say, a
    Black+Hispanic person from a "Black" filter.

    RaceMultiracial — "Included" if 2+ flags are "Yes", with one exception:
    White + Hispanic/Latina/o alone is NOT counted as Multiracial, matching
    how Client_Demographics.ipynb's own RaceAndEthnicity/
    RaceAndEthnicityExpanded columns already treat that specific
    combination (Hispanic/Latina/o is an ethnicity, not a race, and "White
    Hispanic" is a common single-race identification, not a multi-race
    one) — kept consistent with that existing definition rather than
    introducing a second, contradictory meaning of "Multiracial" in the
    same dataset.

    Person-level — call once on Client_Demographics, not per merge. Each of
    these 8 columns is its own clean binary partition (Included + Not
    Included = everyone), even though a person can be "Included" in
    several of the race_* columns AT ONCE — see config.py's own comment on
    why that's handled as 8 separate dimensions rather than one dimension
    with 8 overlapping categories.
    """
    df = df.copy()
    flags = {label: df[col] == "Yes" for label, col in _RACE_FLAG_TO_COLUMN.items()}

    for label, is_selected in flags.items():
        df[f"RaceIncludes_{label}"] = np.where(is_selected, _INCLUDED, _NOT_INCLUDED)

    yes_count = pd.concat(flags.values(), axis=1).sum(axis=1)
    is_white_hl_only = (yes_count == 2) & flags["White"] & flags["HL"]
    is_multiracial = (yes_count >= 2) & ~is_white_hl_only
    df["RaceMultiracial"] = np.where(is_multiracial, _INCLUDED, _NOT_INCLUDED)

    return df
