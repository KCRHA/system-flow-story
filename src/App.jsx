import { useEffect, useMemo, useState } from "react";
import { loadDashboardData, filterRows, distinctValues } from "./lib/loadData.js";
import { DEMOGRAPHIC_TYPES } from "./components/FilterBar.jsx";
import { yearsIn } from "./lib/sankeyData.js";
import LengthSection from "./components/sections/LengthSection.jsx";
import OutflowSection from "./components/sections/OutflowSection.jsx";
import CapacitySection from "./components/sections/CapacitySection.jsx";

// "Race / Ethnicity" is the one demographic type that isn't a 1-to-1 stand-in
// for a single pipeline dimension — each race is its own independent binary
// dimension (see config.py's RACE_DIMENSIONS), so a person can be
// "Included" in more than one at once (e.g. Black AND Hispanic/Latina/o).
// This maps the visible category label picked in the UI to the real
// (dimension, category) pair the data is actually keyed by — every other
// demographic type already has dimension === type, category === the
// picked label, so this is the one place that distinction matters.
const RACE_ETHNICITY_CATEGORY_DIMENSIONS = {
  "American Indian, Alaska Native, or Indigenous": "race_aian",
  "Asian or Asian American": "race_asian",
  "Black, African American, or African": "race_black",
  "Native Hawaiian or Pacific Islander": "race_nhpi",
  White: "race_white",
  "Hispanic/Latina/o": "race_hl",
  "Middle Eastern or North African": "race_mena",
  Multiracial: "race_multiracial",
};

// Hidden from every demographic type's category dropdown for now — a
// deliberate, revisitable choice (not a data error) to keep "we don't know"
// buckets out of the filter until there's a considered way to present them.
// Covers GenderIdentity/GenderAlignment's "Unknown" (see demographics.py)
// and age_category's "Undefined" (EpisodeAgeTier/AgeTierAtEnrollment rows
// with no usable birth date — see build_flow.py).
const HIDDEN_CATEGORIES = new Set(["Unknown", "Undefined"]);

// Age tiers read youngest-to-oldest, not alphabetically — a plain .sort()
// puts "Under 18" last (after "65+"), since alphabetical sort treats digits
// before "U". Any category not in this list (there shouldn't be any once
// HIDDEN_CATEGORIES is filtered out) is dropped rather than silently
// inserted in an arbitrary spot.
const AGE_CATEGORY_ORDER = ["Under 18", "18 to 24", "25 to 34", "35 to 44", "45 to 54", "55 to 64", "65+"];

function resolveDemographicScope(demographicType, demographicCategory) {
  if (demographicType === "race_ethnicity") {
    return { dimension: RACE_ETHNICITY_CATEGORY_DIMENSIONS[demographicCategory], category: "Included" };
  }
  return { dimension: demographicType, category: demographicCategory };
}

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [populationSegment, setPopulationSegment] = useState("all_population");
  const [selectedYear, setSelectedYear] = useState(null);
  const [selectedDemographicType, setSelectedDemographicType] = useState("overall");
  const [selectedDemographicCategory, setSelectedDemographicCategory] = useState("Overall");

  useEffect(() => {
    loadDashboardData().then(setData).catch(setError);
  }, []);

  // Derived from dashboard_flow_monthly (the most granular source) —
  // capacity/length/return-cohort data all share the same export window
  // (see get_export_window in the pipeline), so this year list applies
  // across every section that uses one.
  const years = useMemo(() => {
    if (!data) return [];
    return yearsIn(filterRows(data.flow, { populationSegment, dimension: "overall", category: "Overall" }));
  }, [data, populationSegment]);
  // Falls back to the most recent available year whenever the current
  // selection isn't valid (first load, or a population switch whose data
  // spans a different range of years).
  const year = years.includes(selectedYear) ? selectedYear : years[0] ?? null;

  // age_category isn't offered for the YYA population segment — everyone in
  // it already falls in the same one or two age tiers by definition, so
  // breaking it down further is meaningless (see FilterBar.jsx's own
  // comment on DEMOGRAPHIC_TYPES).
  const demographicTypeOptions = useMemo(
    () => (populationSegment === "yya" ? DEMOGRAPHIC_TYPES.filter((opt) => opt.value !== "age_category") : DEMOGRAPHIC_TYPES),
    [populationSegment]
  );
  // Same fallback pattern as `year` above — lands back on "All" whenever
  // the current selection isn't valid for the freshly chosen population
  // (i.e. Age Category was selected, then the population switched to YYA).
  const demographicType = demographicTypeOptions.some((opt) => opt.value === selectedDemographicType)
    ? selectedDemographicType
    : "overall";

  // Every category dashboard_flow_monthly carries for the selected
  // demographic type — data-derived, not hardcoded, so it always matches
  // what the export actually contains (see distinctValues/filterRows,
  // loadData.js). "overall" only ever has "Overall". "race_ethnicity" is
  // the one exception: its 8 visible categories are fixed labels (see
  // RACE_ETHNICITY_CATEGORY_DIMENSIONS above), not derived from any single
  // dimension's own distinct category values, since there is no single
  // "race_ethnicity" dimension in the data anymore.
  const demographicCategories = useMemo(() => {
    if (!data || demographicType === "overall") return ["Overall"];
    if (demographicType === "race_ethnicity") return Object.keys(RACE_ETHNICITY_CATEGORY_DIMENSIONS);
    const categories = distinctValues(filterRows(data.flow, { dimension: demographicType }), "category").filter(
      (category) => !HIDDEN_CATEGORIES.has(category)
    );
    if (demographicType === "age_category") {
      return AGE_CATEGORY_ORDER.filter((category) => categories.includes(category));
    }
    return categories.sort();
  }, [data, demographicType]);
  // Same fallback pattern as `year` above — lands on the first available
  // category whenever the current selection isn't valid for the freshly
  // chosen demographic type.
  const demographicCategory = demographicCategories.includes(selectedDemographicCategory)
    ? selectedDemographicCategory
    : demographicCategories[0] ?? "Overall";
  // The real (dimension, category) pair the data is filtered by — distinct
  // from demographicType/demographicCategory above, which are what the
  // dropdowns show and what the blurb text displays (see
  // resolveDemographicScope's own comment).
  const { dimension: filterDimension, category: filterCategory } = resolveDemographicScope(demographicType, demographicCategory);

  if (error) return <div className="hero">Couldn't load dashboard data: {error.message}</div>;
  if (!data) return <div className="hero">Loading…</div>;

  return (
    <div>
      <header className="hero">
        <h1>King County's Homelessness System Flow</h1>
        <p>
          Data is one of our most powerful tools for ending homelessness. This dashboard follows how people move
          into, through, and out of King County's homelessness response system: who enters, who's active, who
          exits and to where, how much shelter and housing capacity exists to meet the need, and how long people
          experience homelessness.
        </p>
      </header>
      <OutflowSection
        flowYearlyRows={data.flowYearly}
        flowQuarterlyRows={data.flowQuarterly}
        flowMonthlyRows={data.flow}
        populationSegment={populationSegment}
        onPopulationChange={setPopulationSegment}
        years={years}
        year={year}
        onYearChange={setSelectedYear}
        demographicType={demographicType}
        onDemographicTypeChange={setSelectedDemographicType}
        demographicTypeOptions={demographicTypeOptions}
        demographicCategory={demographicCategory}
        onDemographicCategoryChange={setSelectedDemographicCategory}
        demographicCategoryOptions={demographicCategories}
        filterDimension={filterDimension}
        filterCategory={filterCategory}
      />
      <CapacitySection
        capacityRows={data.capacity}
        capacityQuarterlyRows={data.capacityQuarterly}
        capacityYearlyRows={data.capacityYearly}
        year={year}
        demographicType={demographicType}
      />
      <LengthSection
        lengthRows={data.length}
        returnCohortRows={data.returnCohorts}
        populationSegment={populationSegment}
        demographicType={demographicType}
        demographicCategory={demographicCategory}
        filterDimension={filterDimension}
        filterCategory={filterCategory}
        year={year}
      />
      <footer className="data-footnote">
        <p>
          <strong>*</strong> and <strong>**</strong> mark numbers withheld to protect individual privacy, not a
          value of zero. <strong>*</strong> means the true count is too small (fewer than 11 people) to show
          without risking identifying someone. <strong>**</strong> means the value that would normally be shown
          here is 11 people or more, but showing it would make a nearby suppressed number (fewer than 11 people)
          calculable, so it's hidden too.
        </p>
      </footer>
    </div>
  );
}
