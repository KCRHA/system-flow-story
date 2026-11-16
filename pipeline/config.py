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

# "We don't know" buckets (GenderIdentity/GenderAlignment/LastKnownSubregion/
# age "Unknown", people with no client_demographic row). The dashboard never
# shows them, so they're never written to the JSON and never suppressed
# themselves. They still take part in suppression as hidden cells
# (suppression.UNPUBLISHED_MARKER): to a reader they're "0 or more", which
# already stops the other categories from adding up to the overall row, so
# most groups need no secondary at all. Their own value may be derivable
# (overall minus the categories); that's fine, since it counts people whose
# characteristic is unknown, not people who have one.
UNPUBLISHED_CATEGORIES = frozenset({"Unknown", "Undefined"})

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
    "seniors": "Senior",
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

# "age_category" is native to episode_systemwide (EpisodeAgeTier -- see the
# Episode_Systemwide notebook's age-at-episode-start computation and
# population.py's YYA branch, which already reads this same column), not a
# derived rollup. It's episode-scoped rather than a true
# person-level constant (age tier can differ between two of a person's own episodes over
# the export window) -- see build_flow.py's EPISODE_SCOPED_CATEGORY_DIMENSIONS,
# which resolves its categories fresh per period rather than
# from a single whole-window snapshot, for the same reason. For the YYA
# population segment, the frontend (see FilterBar.jsx/App.jsx) restricts this
# filter's options to the tiers YYA can actually contain ("0 to 11",
# "12 to 17", "18 to 24") instead of hiding it outright.
#
# "unsheltered_in_period" (see DIMENSION_COLUMNS' own comment) is
# deliberately NOT included in this shared list, even though it's a real
# dimension in dashboard_flow_monthly/yearly/quarterly — build_length.py and
# build_return_cohorts.py both iterate this exact list and expect every
# entry to already be a standing column on episode_systemwide, which
# "unsheltered_in_period" isn't and can't be (it's an OR across whichever
# period is currently being built, not a fixed per-row value). build_flow.py
# adds it on top of this list locally instead — see its own FLOW_DIMENSIONS.
DIMENSIONS = [
    "overall",
    *RACE_DIMENSIONS,
    "gender_identity",
    "gender_alignment",
    "age_category",
    "last_known_subregion",
    # "last_known_city",  # last_known_city filter temporarily disabled
]

# --- Household type (dashboard_flow_monthly "household_type_*" dimensions) ---
# One independent binary ("Included"/"Not Included") dimension per HUD
# household type, same pattern as PROJECT_ENGAGEMENT_GROUPS: a person is
# Included if ANY of their episode_systemwide rows in the period being built
# has that EpisodeHouseholdType (the most common HUD HouseholdType across
# the episode's events). Categories overlap: someone in a family episode in
# March and an adults-only episode in September is Included in both for
# that year. Chosen by the dashboard owner (2026-11-16) over "latest episode
# wins" so that "Adults and Children" for All population matches the
# Families with Children population total. Rows with any other value
# (null/unknown) simply aren't Included anywhere, so there's no unknown
# bucket to hide. See period_dimensions.py's _household_type_category.
HOUSEHOLD_TYPE_GROUPS = {
    "household_type_adults_children": "Household with Children and Adults",
    "household_type_adults_only": "Household without Children",
    "household_type_children_only": "Household with Only Children",
}
HOUSEHOLD_TYPE_DIMENSIONS = list(HOUSEHOLD_TYPE_GROUPS)

# Dimensions never built for a population segment because the dashboard
# doesn't offer them there — keep in sync with App.jsx's
# HOUSEHOLD_TYPE_HIDDEN_SEGMENTS/RESTRICTED_HOUSEHOLD_TYPES. Single Adults and
# Families are themselves defined by household composition, so household
# type would only restate the segment; seniors and veterans are adults, so
# they can't be in a children-only household. Every build_*.py per-segment
# dimension loop goes through dimensions_for_segment, so these rows are
# never computed or published.
SEGMENT_SKIPPED_DIMENSIONS = {
    "single_adults": frozenset(HOUSEHOLD_TYPE_DIMENSIONS),
    "family": frozenset(HOUSEHOLD_TYPE_DIMENSIONS),
    "seniors": frozenset({"household_type_children_only"}),
    "veterans": frozenset({"household_type_children_only"}),
}


def dimensions_for_segment(segment_key: str, dimensions: list) -> list:
    """`dimensions` minus whatever SEGMENT_SKIPPED_DIMENSIONS skips for this segment."""
    skipped = SEGMENT_SKIPPED_DIMENSIONS.get(segment_key, frozenset())
    return [d for d in dimensions if d not in skipped]

# last_known_city filter temporarily disabled — commented out along with
# DIMENSIONS/DIMENSION_COLUMNS' own entries, export.py's LastKnownCity
# handling, and build_flow.py's enrollment merge column.
# The 10 King County cities with the highest population (2020 Census /
# 2024 OFM estimates — Seattle, Bellevue, Kent, Renton, Federal Way,
# Kirkland, Redmond, Auburn, Sammamish, Shoreline, in that order), used by
# export.py to restrict last_known_city's raw, free-text LastKnownCity
# value down to a fixed, small set of categories. Anyone whose last known
# city isn't one of these ten (a smaller KC city, somewhere outside King
# County entirely, or never collected) is collapsed to "Other" rather than
# left as its own one-off category — unlike last_known_subregion, the raw
# city column has no bounded set of values on its own, so without this the
# dimension would blow up into one category per distinct city name ever
# recorded. Order here is reused by App.jsx's LAST_KNOWN_CITY_ORDER to sort
# the frontend dropdown by population rather than alphabetically.
# TOP_10_KING_COUNTY_CITIES = [
#     "Seattle",
#     "Bellevue",
#     "Kent",
#     "Renton",
#     "Federal Way",
#     "Kirkland",
#     "Redmond",
#     "Auburn",
#     "Sammamish",
#     "Shoreline",
# ]

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

# project_engaged_ce counts CESP enrollments only (the CE priority pool, same
# IDs as Episode_CE.ipynb's CESP_PROGRAM_IDS), not every ProjectTypeCode 14
# project — confirmed with the dashboard owner (2026-11-09). A dimension
# listed here keeps only enrollments in these ProgramIDs, on top of its
# ProjectTypeCode filter above.
PROJECT_ENGAGEMENT_PROGRAM_IDS = {
    "project_engaged_ce": {"4213", "4240", "4244"},
}

# --- Subregion engagement (dashboard_flow_monthly "engaged_in_subregion_*"
# dimensions) ---
# Like PROJECT_ENGAGEMENT_GROUPS immediately above, these 7 groups are
# deliberately NOT mutually exclusive — a person can access services in more
# than one subregion within the same period (e.g. Seattle Metro AND South
# King County in the same month), so each is its own independent binary
# ("Included"/"Not Included") dimension rather than one dimension with 7
# overlapping categories, same reasoning as RACE_DIMENSIONS/
# PROJECT_ENGAGEMENT_GROUPS above.
#
# Sourced from event_systemwide, NOT All_Program_Enrollments — "engaged in
# subregion X" means the person has an event_systemwide row with
# ClientStatus == "Homeless" whose EventDate falls anywhere within the
# period being built, joined to program_attributes.Subregion via ProgramID.
# Deliberately a discrete event log, not an enrollment date-span: the
# request behind this was "which subregion(s) did someone access services
# in," a question about where homelessness-indicating events actually
# happened, not which program spans were open.
#
# Values confirmed directly against program_addresses_by_pID.xlsx (the
# manually-maintained, pre-geocoded source Program_Attributes.ipynb's own
# Subregion column is taken from verbatim, 2026-11-02): these 6 named King
# County subregions, plus "Pierce County," "Urban Unincorporated," and a
# handful of blank/ungeocoded rows, all deliberately left out of this dict
# (confirmed with the dashboard owner, 2026-11-02, that Urban Unincorporated
# programs should be excluded from this breakdown entirely, same reasoning
# as Pierce County being out of scope for a King County-focused dashboard) —
# a program excluded this way simply can't make anyone "Included" via that
# event; they still count normally for any OTHER qualifying event they have.
# "South East King County" (with the internal space) is the literal
# spreadsheet value, not a typo — it differs from LastKnownSubregion's own
# "Southeast King County" (one word), a separate, unrelated lookup
# (kc_place_subregions.csv) that this dimension does NOT use.
#
# Computed fresh per period, same "OR across every row in the period"
# contract as unsheltered_in_period/project_engaged_* — see
# period_dimensions.py's _subregion_engagement_category and
# PERIOD_AGGREGATE_CATEGORY_DIMENSIONS.
SUBREGION_ENGAGEMENT_GROUPS = {
    "engaged_in_subregion_east": "East King County",
    "engaged_in_subregion_north": "North King County",
    "engaged_in_subregion_seattle": "Seattle Metro",
    "engaged_in_subregion_snoqualmie": "Snoqualmie Valley",
    "engaged_in_subregion_south": "South King County",
    "engaged_in_subregion_southeast": "South East King County",
}
SUBREGION_ENGAGEMENT_DIMENSIONS = list(SUBREGION_ENGAGEMENT_GROUPS)

# --- Capacity subregion scoping (dashboard_capacity_*'s "subregion" column) ---
# build_capacity.py has no per-person dimension to filter by at all (it's
# aggregate program inventory data, not person-level — see its own module
# docstring), but it can be scoped by program_attributes.Subregion directly,
# a program-location fact rather than a person one. Confirmed with the
# dashboard owner (2026-11-02) that it makes sense for the frontend's two
# person-level subregion filters (last_known_subregion, engaged_in_subregion)
# to ALSO scope Capacity this way when either is active — "show capacity for
# programs in Seattle Metro" — even though neither filter's own underlying
# question ("where does this person live" / "where did this person get
# served") is really about program location. See CapacitySection.jsx.
#
# Maps every literal program_attributes.Subregion value this dashboard
# treats as in-scope to its display spelling. "South East King County" (two
# words) is program_attributes' own literal spelling (see
# SUBREGION_ENGAGEMENT_GROUPS' comment above) — normalized to "Southeast
# King County" (one word) here so dashboard_capacity_*'s own subregion
# column reads identically to last_known_subregion's/engaged_in_subregion's
# category labels, letting the frontend filter by a single shared string
# with no separate label-mapping table of its own. Pierce County/Urban
# Unincorporated/ungeocoded programs are deliberately left out — they still
# count toward every "Overall" (unscoped) row, same totals this table always
# published, but don't get their own subregion row since neither is a
# selectable category in the frontend.
SUBREGION_DISPLAY_LABELS = {value: value for value in SUBREGION_ENGAGEMENT_GROUPS.values()}
SUBREGION_DISPLAY_LABELS["South East King County"] = "Southeast King County"

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
    "age_category": "EpisodeAgeTier",
    # Native client_demographic column (Client_Demographics.ipynb's own
    # city -> subregion mapping), person-level like VeteranStatus/the
    # race_*/gender_* rollups above, not episode-scoped. Anyone with no
    # mappable King County subregion (last known address outside King
    # County, in an unincorporated area, or never collected) gets NaN from
    # that notebook — filled to "Unknown" in export.py's client_demographics
    # load, same as GenderIdentity's own "Unknown" bucket, so this dimension
    # still partitions cleanly for suppression. "Unknown" is then never
    # published (UNPUBLISHED_CATEGORIES above).
    "last_known_subregion": "LastKnownSubregion",
    # last_known_city filter temporarily disabled — see DIMENSIONS above and
    # export.py's LastKnownCity handling.
    # Also a native client_demographic column (Client_Demographics.ipynb's
    # own free-text last-known-city value, the input to its city -> subregion
    # mapping above), restricted in export.py's client_demographics load to
    # TOP_10_KING_COUNTY_CITIES — everyone else (a smaller city, outside King
    # County, or never collected) is collapsed to "Other" there, same
    # "Unknown" bucket reasoning as last_known_subregion but a different
    # label since this isn't a data-completeness gap for most of them, just
    # a city outside the top 10. "Other" is hidden from the frontend filter
    # the same way "Unknown" is — see App.jsx's LAST_KNOWN_CITY_ORDER.
    # "last_known_city": "LastKnownCity",
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
    # Same story as project_engaged_* immediately above, one synthetic
    # column per SUBREGION_ENGAGEMENT_GROUPS entry — computed fresh per
    # period in period_dimensions.py's _subregion_engagement_category, from
    # event_systemwide joined to program_attributes, not a standing
    # episode_systemwide column.
    "engaged_in_subregion_east": "EngagedInSubregionEastKingCounty",
    "engaged_in_subregion_north": "EngagedInSubregionNorthKingCounty",
    "engaged_in_subregion_seattle": "EngagedInSubregionSeattleMetro",
    "engaged_in_subregion_snoqualmie": "EngagedInSubregionSnoqualmieValley",
    "engaged_in_subregion_south": "EngagedInSubregionSouthKingCounty",
    "engaged_in_subregion_southeast": "EngagedInSubregionSoutheastKingCounty",
    # Same story again, one synthetic column per HOUSEHOLD_TYPE_GROUPS entry
    # — computed fresh per period in period_dimensions.py's
    # _household_type_category from episode_systemwide rows.
    "household_type_adults_children": "HouseholdTypeAdultsAndChildren",
    "household_type_adults_only": "HouseholdTypeAdultsOnly",
    "household_type_children_only": "HouseholdTypeChildrenOnly",
}

# --- Inflow / outflow / active flow_type values (dashboard_flow_monthly) ---
INFLOW_TYPE_MAP = {
    "Newly Homeless": "newly_homeless",
    "Return from Housed": "return_from_housed",
    "Return from Inactive": "return_from_inactive",
}
# HUD outflow reason -> exit key. The length-of-time tables use this as is:
# their by-exit "inactive" panel deliberately excludes deceased.
OUTFLOW_TYPE_MAP = {
    "Permanently Housed": "permanently_housed",
    "Inactive": "inactive",
    "Deceased": "deceased",
}
DECEASED_HUD_VALUE = "Deceased"

# The flow tables (sankey, KPI cards, trend chart) fold Deceased into
# Inactive: on its own, deceased was the smallest outflow and the single
# biggest cause of suppression. How many of an Inactive count are deceased
# is published only as a band of DECEASED_BAND_WIDTH (1-10, 11-20, ...)
# under DECEASED_IN_INACTIVE_FLOW_TYPE — see suppression.apply_deceased_bands.
FLOW_OUTFLOW_BUCKET_MAP = {
    "Permanently Housed": "permanently_housed",
    "Inactive": "inactive",
    DECEASED_HUD_VALUE: "inactive",
}
DECEASED_IN_INACTIVE_FLOW_TYPE = "deceased_in_inactive"
DECEASED_BAND_WIDTH = 10

# Length-of-time tables publish every group with at least one person (no
# small-cell suppression, and n itself is never published), but a group
# smaller than this gets only its median: with three or fewer people, the
# percentiles and mean give away individual durations (user raised 3 -> 4).
LENGTH_FULL_STATS_MIN_N = 4

# HUD ProjectTypeCode legend (see Event_Systemwide_2026_01_21.ipynb header, and
# confirmed again directly against All_Program_Enrollments_2026_01_22.ipynb,
# which carries this same ProjectTypeCode column):
# 0=ES-EE, 1=ES-NBN, 2=TH, 3=PSH, 4=SO, 8=Safe Haven, 9=PH-Housing Only,
# 10=PH-Housing w/Services, 12=Prevention, 13=RRH, 14=CE

# program_attributes.ProjectTypeCode and all_program_enrollments.ProjectTypeCode
# store the human-readable HUD label in Synapse, not the numeric HUD code
# used everywhere else in this pipeline (episode_systemwide's
# EpisodeInflowType/OutflowType etc. are already numeric-code-free text of
# their own kind, but ProjectTypeCode specifically is numeric in the source
# notebooks this was ported from) — confirmed directly against both tables'
# distinct values, which are exactly these 14 HUD labels. Map to numeric so
# PROJECT_ENGAGEMENT_GROUPS/CAPACITY_PROJECT_TYPE_GROUPS below (and their
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

def get_export_window(today: date | None = None) -> tuple[date, date]:
    """Rolling window: last 5 completed calendar years, plus completed months
    of the current year (no partial/in-progress month). Recomputed on every
    pipeline run so the export window doesn't need a manual date update."""
    today = today or date.today()
    # TEMPORARY: hardcoded to 2019 instead of the usual rolling
    # today.year - 5 start (which would currently land on 2021) — revert to
    # the rolling calculation below once this lookback is no longer needed.
    start = date(2019, 1, 1)
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
