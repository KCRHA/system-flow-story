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
POPULATION_SEGMENTS = {
    "all_population": "All",
    "yya": "Youth and Young Adults",
    "chronic": "Chronic",
    "single_adults": "Single Adults",
    "veterans": "Veteran",
}

# --- Disaggregation dimensions (dashboard_flow_monthly.dimension) ---
DIMENSIONS = ["overall", "race_ethnicity", "gender", "household_type"]

# episode_systemwide column carrying each dimension's category value
DIMENSION_COLUMNS = {
    "race_ethnicity": "RaceAndEthnicity",  # summary rollup, not *Expanded
    "gender": "Gender",  # summary rollup, not *Expanded
    "household_type": "EpisodeHouseholdType",
}

# All_Program_Enrollments' equivalent columns (confirmed against
# All_Program_Enrollments_2026_01_22.ipynb's final columns_to_select —
# RaceAndEthnicity/Gender aren't native to that table and must be joined in
# from Client_Demographics on PersonalID first; HouseholdType is native).
ENROLLMENT_DIMENSION_COLUMNS = {
    "race_ethnicity": "RaceAndEthnicity",
    "gender": "Gender",
    "household_type": "HouseholdType",
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
