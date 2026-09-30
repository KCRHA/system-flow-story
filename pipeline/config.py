"""Shared constants for the dashboard export pipeline.

Column names and the upstream 730-day "Return from Housed" gap threshold
are confirmed against the actual notebook code in DataHubDevelopment
(Episode_Systemwide, Client_Demographics, Program_Attributes,
Program_Performance_Metrics, Episode_CE) — see the project README for
citations. This dashboard's own RETURN_WINDOW_DAYS below is a separate,
narrower value (see its own comment). Nothing here should need to
reference the old methodology deck.
"""
from datetime import date

# --- Small-cell suppression (see suppression.py) ---
SUPPRESSION_THRESHOLD = 11  # HUD convention: suppress any nonzero cell under this count — zero is never suppressed

# Suppressed counts are never published (not even rounded) — the marker is
# what a reader sees instead of a number. "*" = primary (below threshold on
# its own). "**" = secondary/complementary (suppressed to prevent a *
# neighbor in the same group from being recovered by arithmetic).
PRIMARY_SUPPRESSION_MARKER = "*"
SECONDARY_SUPPRESSION_MARKER = "**"

# --- Return-to-homelessness window ---
# How soon after a permanent-housing exit a new episode counts as a
# "return" for dashboard_return_cohorts — 6 months, not the 730-day gap
# episode_systemwide's own determine_inflow_type() uses to classify
# "Return from Housed" vs "Newly Homeless" upstream. That 730-day source
# threshold is broader (a superset): any return within our narrower
# 182-day window is necessarily also within 730 days, so it's still
# correctly labeled "Return from Housed" in the source data and this
# window can safely filter from it. Also drives window_complete (a
# cohort's return rate isn't reportable until this many days have
# elapsed since its exit month).
RETURN_WINDOW_DAYS = 182

# --- Population segments (dashboard_flow_monthly.population_segment) ---
# Maps dashboard segment names -> the filter_population() label used in
# DataHubDevelopment/Systemwide/BFZ_Monthly_Report notebooks.
#
# "family" is deliberately defined from the raw HouseholdType/
# EpisodeHouseholdType value ("Household with Children and Adults"), not
# from HouseholdCategory — HouseholdCategory forces every household into
# exactly one bucket (Family with Children wins over Youth and Young
# Adults in its own priority order), which would silently undercount YYA
# families if used here. A household with both a young parent and a
# child is legitimately both "family" and "YYA" at once, the same way
# every other segment already overlaps (e.g. a chronic veteran) — see
# population.py's Family branch.
POPULATION_SEGMENTS = {
    "all_population": "All",
    "yya": "Youth and Young Adults",
    "chronic": "Chronic",
    "single_adults": "Single Adults",
    "veterans": "Veteran",
    "family": "Family",
}

# --- Disaggregation dimensions (dashboard_flow_monthly.dimension) ---
# "gender_identity"/"gender_alignment" are rollups computed from
# Client_Demographics's GenderExpanded column (see demographics.py) — not
# native columns like EpisodeHouseholdType. They replace a prior plain
# "gender" dimension (the raw single-select/summary Gender column), which
# was never actually surfaced anywhere in the frontend.
#
# The 8 "race_*" dimensions replace a prior single "race_ethnicity"
# dimension (the plain RaceAndEthnicity summary column, which collapsed
# anyone selecting 2+ races into one generic "Multiracial" bucket). Each is
# its own independent binary ("Included"/"Not Included") dimension, derived
# straight from the 7 raw RaceAndEthnicity_* flags plus one Multiracial
# flag — see demographics.py's compute_race_rollups. Deliberately NOT one
# dimension with 8 overlapping categories: a person can be "Included" in
# more than one of these at once (e.g. Black AND Hispanic/Latina/o), which
# the rest of this pipeline's suppression logic assumes never happens
# within a single dimension (categories must partition the population —
# see suppression.py). Eight independent binary dimensions each keep that
# partition property on their own (Included + Not Included = everyone),
# so no suppression changes were needed to add them.
RACE_DIMENSIONS = ["race_aian", "race_asian", "race_black", "race_nhpi", "race_white", "race_hl", "race_mena", "race_multiracial"]

# "age_category" is native to both source tables (EpisodeAgeTier /
# AgeTierAtEnrollment -- see the Episode_Systemwide notebook's
# age-at-episode-start computation and population.py's YYA branch, which
# already reads these same columns), not a derived rollup, though
# AgeTierAtEnrollment's raw label vocabulary differs from EpisodeAgeTier's
# for the same buckets and is normalized onto it in build_flow.py's
# build_resource_access_rows before use. Like household_type, it's
# episode-scoped rather than a true person-level constant (age tier can
# differ between two of a person's own episodes over the export window) --
# see build_flow.py's EPISODE_SCOPED_CATEGORY_DIMENSIONS, which resolves
# both dimensions' categories fresh per period rather than from a single
# whole-window snapshot, for the same reason. Not offered as a frontend
# filter for the YYA population segment (see FilterBar.jsx): everyone
# there already falls in the same one or two tiers by definition.
#
# "unsheltered_in_period" (see DIMENSION_COLUMNS' own comment) is
# deliberately NOT included in this shared list, even though it's a real
# dimension in dashboard_flow_monthly/yearly/quarterly — build_length.py,
# build_return_cohorts.py, and build_flow.py's own build_resource_access_rows
# all iterate this exact list and expect every entry to already be a
# standing column on their own source dataframe (episode_systemwide /
# All_Program_Enrollments), which "unsheltered_in_period" isn't and can't
# be (it's an OR across whichever period is currently being built, not a
# fixed per-row value) and has no All_Program_Enrollments equivalent at
# all. build_flow.py adds it on top of this list locally instead — see its
# own FLOW_DIMENSIONS.
DIMENSIONS = ["overall", *RACE_DIMENSIONS, "gender_identity", "gender_alignment", "household_type", "age_category"]

# --- Project type engagement (dashboard_flow_monthly "project_engaged_*"
# dimensions) ---
# Like RACE_DIMENSIONS, these 5 groups are deliberately NOT mutually
# exclusive — a person can be engaged with more than one project type within
# the same period (e.g. Street Outreach AND Emergency Shelter in the same
# month), so each is its own independent binary ("Included"/"Not Included")
# dimension rather than one dimension with 5 overlapping categories, same
# reasoning as config.py's RACE_DIMENSIONS comment above. "Housing Programs"
# groups PSH(3), RRH(13), and both generic PH codes (9=Housing Only,
# 10=Housing w/Services) into one bucket — confirmed with the dashboard
# owner (2026-09-29) that "OPH" and "PH" in the original request both refer
# to this same generic-PH pair, not two distinct groups.
#
# Computed fresh per period (month/quarter/year being built), same
# "OR across every row in the period" contract as unsheltered_in_period
# below — never a fixed per-row episode_systemwide value, since project
# type has no episode_systemwide equivalent at all (episode_systemwide is
# episode-level, not enrollment-level). See build_flow.py's
# _project_engagement_category and PERIOD_AGGREGATE_CATEGORY_DIMENSIONS.
PROJECT_ENGAGEMENT_GROUPS = {
    "project_engaged_es": [0, 1, 8],
    "project_engaged_so": [4],
    "project_engaged_housing": [3, 9, 10, 13],
    "project_engaged_th": [2],
    "project_engaged_ce": [14],
}
PROJECT_ENGAGEMENT_DIMENSIONS = list(PROJECT_ENGAGEMENT_GROUPS)

# episode_systemwide column carrying each dimension's category value
DIMENSION_COLUMNS = {
    "race_aian": "RaceIncludes_AIAN",  # derived — see demographics.py
    "race_asian": "RaceIncludes_Asian",
    "race_black": "RaceIncludes_Black",
    "race_nhpi": "RaceIncludes_NHPI",
    "race_white": "RaceIncludes_White",
    "race_hl": "RaceIncludes_HL",
    "race_mena": "RaceIncludes_MENA",
    "race_multiracial": "RaceMultiracial",
    "gender_identity": "GenderIdentity",  # derived — see demographics.py
    "gender_alignment": "GenderAlignment",  # derived — see demographics.py
    "household_type": "EpisodeHouseholdType",
    "age_category": "EpisodeAgeTier",
    # Not a native or Client_Demographics-sourced column like the rest of
    # this map — "Included"/"Not Included" on whether any of a person's
    # episode_systemwide rows within the period being built (month/quarter/
    # year) had LastShelterStatusInTimeframe == "Unsheltered". Computed
    # fresh per period in build_flow.py's _unsheltered_in_period_category,
    # never as a standing column on episode_systemwide itself, so only
    # build_flow.py's own FLOW_DIMENSIONS (not this DIMENSIONS list) actually
    # iterates over it — see FLOW_DIMENSIONS' own comment for why.
    "unsheltered_in_period": "UnshelteredInPeriod",
    # Same story as unsheltered_in_period immediately above, one synthetic
    # column per PROJECT_ENGAGEMENT_GROUPS entry — computed fresh per period
    # in build_flow.py's _project_engagement_category, from
    # All_Program_Enrollments, not a standing episode_systemwide column.
    "project_engaged_es": "ProjectEngagedEmergencyShelter",
    "project_engaged_so": "ProjectEngagedStreetOutreach",
    "project_engaged_housing": "ProjectEngagedHousingPrograms",
    "project_engaged_th": "ProjectEngagedTransitionalHousing",
    "project_engaged_ce": "ProjectEngagedCoordinatedEntry",
}

# All_Program_Enrollments' equivalent columns (confirmed against
# All_Program_Enrollments_2026_01_22.ipynb's final columns_to_select — none
# of the race_*/gender_* derived columns are native to that table and must
# be joined in from Client_Demographics on PersonalID first; HouseholdType
# is native, just under a different name than its episode_systemwide
# counterpart. "age_category" points at "AgeCategory" — a normalized copy
# of the native AgeTierAtEnrollment column build_resource_access_rows adds,
# not the raw column itself — because AgeTierAtEnrollment's own label
# vocabulary doesn't match EpisodeAgeTier's for the same buckets (see
# build_resource_access_rows' own comment); the raw column has to stay
# untouched since filter_population_enrollment's YYA branch depends on its
# literal values.
ENROLLMENT_DIMENSION_COLUMNS = {
    **DIMENSION_COLUMNS,
    "household_type": "HouseholdType",
    "age_category": "AgeCategory",
}

# --- Inflow / outflow / active flow_type values (dashboard_flow_monthly) ---
INFLOW_TYPE_MAP = {
    "Newly Homeless": "newly_homeless",
    "Return from Housed": "return_from_housed",
    "Return from Inactive": "return_from_inactive",
}
OUTFLOW_TYPE_MAP = {
    "Permanently Housed": "permanently_housed",
    "Inactive": "inactive",
    "Deceased": "deceased",
}

# --- Resource access project types (dashboard_flow_monthly resource_* flow_types) ---
RESOURCE_TYPES = ["outreach", "emergency_shelter", "transitional_housing", "rapid_rehousing", "psh", "prevention"]

# HUD ProjectTypeCode legend (see Event_Systemwide_2026_01_21.ipynb header, and
# confirmed again directly against All_Program_Enrollments_2026_01_22.ipynb,
# which carries this same ProjectTypeCode column):
# 0=ES-EE, 1=ES-NBN, 2=TH, 3=PSH, 4=SO, 8=Safe Haven, 9=PH-Housing Only,
# 10=PH-Housing w/Services, 12=Prevention, 13=RRH, 14=CE
#
# Resource-access rollup (6 whiteboard categories) — codes 9/10 (generic
# permanent housing outside PSH) intentionally have no bucket here: the
# whiteboard's resource-access categories don't include a generic PH bucket
# distinct from PSH, so those enrollments simply aren't counted in Table 1's
# resource_* flow_types. They still roll into capacity's "ph" bucket below,
# since Table 3 answers a different question (system-wide PH capacity).
RESOURCE_PROJECT_TYPE_GROUPS = {
    "outreach": [4],
    "emergency_shelter": [0, 1, 8],
    "transitional_housing": [2],
    "rapid_rehousing": [13],
    "psh": [3],
    "prevention": [12],
}

# program_attributes.ProjectTypeCode and all_program_enrollments.ProjectTypeCode
# store the human-readable HUD label in Synapse, not the numeric HUD code
# used everywhere else in this pipeline (episode_systemwide's
# EpisodeInflowType/OutflowType etc. are already numeric-code-free text of
# their own kind, but ProjectTypeCode specifically is numeric in the source
# notebooks this was ported from) — confirmed directly against both tables'
# distinct values, which are exactly these 14 HUD labels. Map to numeric so
# RESOURCE_PROJECT_TYPE_GROUPS/CAPACITY_PROJECT_TYPE_GROUPS below (and their
# bucket-matching functions in build_flow.py/build_capacity.py) can stay
# expressed in HUD codes, matching the legend comment above.
PROJECT_TYPE_CODE_TEXT_TO_HUD = {
    "Emergency Shelter – Entry Exit": 0,
    "Emergency Shelter – Night-by-Night": 1,
    "Transitional Housing": 2,
    "PH – Permanent Supportive Housing (disability required for entry)": 3,
    "Street Outreach": 4,
    "Services Only": 6,
    "Other": 7,
    "Safe Haven": 8,
    "PH – Housing Only": 9,
    "PH – Housing with Services (no disability required for entry)": 10,
    "Day Shelter": 11,
    "Homelessness Prevention": 12,
    "PH – Rapid Re-Housing": 13,
    "Coordinated Entry": 14,
}

# --- Capacity project-type rollup (dashboard_capacity_monthly.project_type) ---
CAPACITY_PROJECT_TYPE_GROUPS = {
    "ph": [3, 9, 10],  # PSH + PH-Housing Only + PH-Housing w/Services
    "th": [2],
    "es": [0, 1, 8],  # ES entry/exit + ES night-by-night + Safe Haven
    "rrh": [13],
}

# --- Coordinated Entry program IDs (episode_ce / CEActive) ---
CE_PROGRAM_IDS = {"4213", "4240", "4244"}  # HUD ProjectTypeCode 14


def get_export_window(today: date | None = None) -> tuple[date, date]:
    """Rolling window: last 5 completed calendar years, plus completed months
    of the current year (no partial/in-progress month). Recomputed on every
    pipeline run so the export window doesn't need a manual date update."""
    today = today or date.today()
    start = date(today.year - 5, 1, 1)
    # "completed months" excludes the current, still-in-progress month
    if today.month == 1:
        end = date(today.year - 1, 12, 1)
    else:
        end = date(today.year, today.month - 1, 1)
    return start, end


def month_before(d: date) -> date:
    """The 1st of the calendar month immediately before `d`'s own month —
    used to pull one extra lookback month of episode_systemwide ahead of
    the export window's start, so build_flow_rows/build_flow_yearly_rows
    can resolve a true prior_month for the window's first published
    month/year (see export.py's episodes_with_lookback). Never itself
    published; window_start still gates what actually gets emitted."""
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)
