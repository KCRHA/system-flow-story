import { useEffect, useMemo, useState } from "react";
import { loadDashboardData, loadMonthlyFlowForYear, filterRows, distinctValues } from "./lib/loadData.js";
import { DEMOGRAPHIC_TYPES } from "./components/FilterBar.jsx";
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

// unsheltered_in_period's real categories are "Included"/"Not Included" —
// the same generic Included/Not Included convention every other binary
// dimension in the pipeline uses (see config.py's RACE_DIMENSIONS), not a
// label written for display. Same fix as RACE_ETHNICITY_CATEGORY_DIMENSIONS
// above: show a real label in the dropdown, translate it back to the
// dimension's actual category value in resolveDemographicScope.
const UNSHELTERED_CATEGORY_LABELS = {
  "Unsheltered this period": "Included",
  "Not unsheltered this period": "Not Included",
};

// Same pattern as RACE_ETHNICITY_CATEGORY_DIMENSIONS above: project type
// engagement is 5 independent binary dimensions (see pipeline/config.py's
// PROJECT_ENGAGEMENT_GROUPS), not one dimension with 5 overlapping
// categories, since a person can be engaged with more than one project
// type in the same period (e.g. Street Outreach AND Emergency Shelter).
// "Engaged" here means the person had an enrollment of that project type
// overlapping ANY part of the currently selected time period, not just one
// still open at the period's end. "Housing Programs" bundles PSH, RRH, and
// both generic PH types (Housing Only + Housing with Services).
const PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS = {
  "Emergency Shelter": "project_engaged_es",
  "Street Outreach": "project_engaged_so",
  "Housing Programs": "project_engaged_housing",
  "Transitional Housing": "project_engaged_th",
  "Coordinated Entry": "project_engaged_ce",
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
  if (demographicType === "unsheltered_in_period") {
    return { dimension: demographicType, category: UNSHELTERED_CATEGORY_LABELS[demographicCategory] };
  }
  if (demographicType === "project_type_engagement") {
    return { dimension: PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS[demographicCategory], category: "Included" };
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
  // The end of OutflowSection's own quarter/month drill-down, bubbled up via
  // its onPeriodEndMonthChange (see that component's own comment) — null in
  // its Full Year view. LengthSection's "by last housing status" small
  // multiples use this to end their trailing window at the same point
  // Outflow's own KPI cards/run chart already do, instead of always running
  // to the selected Year's end.
  const [periodEndMonth, setPeriodEndMonth] = useState(null);
  // The exact month/quarter OutflowSection's own pills have drilled into
  // (both null in its Full Year view) — see its onSelectedPeriodChange
  // comment. LengthSection's headline KPI card uses this to re-scope to the
  // same period every other KPI card on the page already does, instead of
  // always showing the selected Year's pooled number.
  const [selectedPeriod, setSelectedPeriod] = useState({ quarter: null, month: null });

  useEffect(() => {
    loadDashboardData().then(setData).catch(setError);
  }, []);

  // Derived from dashboard_flow_yearly — capacity/length/return-cohort data
  // all share the same export window (see get_export_window in the
  // pipeline), so this year list applies across every section that uses
  // one. Deliberately not dashboard_flow_monthly: that export is too large
  // to publish on every deploy target (see loadData.js), and yearly covers
  // the exact same year range since it's aggregated from it.
  const years = useMemo(() => {
    if (!data) return [];
    return [...new Set(filterRows(data.flowYearly, { populationSegment, dimension: "overall", category: "Overall" }).map((r) => r.year))].sort(
      (a, b) => b - a
    );
  }, [data, populationSegment]);
  // Falls back to the most recent available year whenever the current
  // selection isn't valid (first load, or a population switch whose data
  // spans a different range of years).
  const year = years.includes(selectedYear) ? selectedYear : years[0] ?? null;

  // dashboard_flow_monthly is pre-split one file per year (~35-45MB each —
  // see loadData.js's loadMonthlyFlowForYear), so only the currently
  // selected year's rows are ever fetched, and each year fetched once is
  // kept here rather than re-fetched on every switch back to it. A year
  // not yet in the cache resolves to OutflowSection's flowMonthlyRows as
  // [] (see MonthPills, which renders an empty pill row rather than
  // crashing) while its fetch is in flight, not undefined/broken.
  const [monthlyFlowByYear, setMonthlyFlowByYear] = useState({});
  useEffect(() => {
    if (year == null || monthlyFlowByYear[year]) return;
    let cancelled = false;
    loadMonthlyFlowForYear(year).then((rows) => {
      if (!cancelled) setMonthlyFlowByYear((prev) => ({ ...prev, [year]: rows }));
    });
    return () => {
      cancelled = true;
    };
  }, [year, monthlyFlowByYear]);
  const monthlyFlowLoading = year != null && !monthlyFlowByYear[year];

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

  // Every category dashboard_flow_quarterly carries for the selected
  // demographic type — data-derived, not hardcoded, so it always matches
  // what the export actually contains (see distinctValues/filterRows,
  // loadData.js). "overall" only ever has "Overall". "race_ethnicity" is
  // the one exception: its 8 visible categories are fixed labels (see
  // RACE_ETHNICITY_CATEGORY_DIMENSIONS above), not derived from any single
  // dimension's own distinct category values, since there is no single
  // "race_ethnicity" dimension in the data anymore. Deliberately not
  // dashboard_flow_monthly: quarterly carries the same dimension/category
  // coverage and is small enough to publish on every deploy target (see
  // loadData.js).
  const demographicCategories = useMemo(() => {
    if (!data || demographicType === "overall") return ["Overall"];
    if (demographicType === "race_ethnicity") return Object.keys(RACE_ETHNICITY_CATEGORY_DIMENSIONS);
    // Same reasoning as race_ethnicity above: fixed display labels, not
    // derived from the dimension's own raw Included/Not Included values.
    if (demographicType === "unsheltered_in_period") return Object.keys(UNSHELTERED_CATEGORY_LABELS);
    if (demographicType === "project_type_engagement") return Object.keys(PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS);
    const categories = distinctValues(filterRows(data.flowQuarterly, { dimension: demographicType }), "category").filter(
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
      </header>
      <section className="section intro-section">
        <p>
          Data is one of our most powerful tools for ending homelessness. This dashboard follows how people move
          into, through, and out of King County's homelessness response system: who enters, who's active, who
          exits and to where, how much shelter and housing capacity exists to meet the need, and how long people
          experience homelessness.
        </p>
        <p>
          On this page, you'll see, for a selected time frame, how many people are moving from intake to services to
          exit, and how long that process takes. To see how the different parts of the system work together, you'll
          also find shelter and housing program capacity and utilization rates here, framed the same system-flow
          way. Together, this gives an integrated view of both people's experience and the system's capacity to meet
          it.
        </p>
      </section>
      <OutflowSection
        flowYearlyRows={data.flowYearly}
        flowQuarterlyRows={data.flowQuarterly}
        flowMonthlyRows={monthlyFlowByYear[year] ?? []}
        flowMonthlyLoading={monthlyFlowLoading}
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
        onPeriodEndMonthChange={setPeriodEndMonth}
        onSelectedPeriodChange={setSelectedPeriod}
      />
      <LengthSection
        lengthRows={data.length}
        lengthByExitRows={data.lengthByExit}
        lengthHeadlineRows={data.lengthHeadline}
        lengthHeadlineMonthlyRows={data.lengthHeadlineMonthly}
        lengthHeadlineQuarterlyRows={data.lengthHeadlineQuarterly}
        returnCohortRows={data.returnCohorts}
        populationSegment={populationSegment}
        demographicType={demographicType}
        demographicCategory={demographicCategory}
        filterDimension={filterDimension}
        filterCategory={filterCategory}
        year={year}
        periodEndMonth={periodEndMonth}
        selectedQuarter={selectedPeriod.quarter}
        selectedMonth={selectedPeriod.month}
      />
      <CapacitySection
        capacityRows={data.capacity}
        capacityQuarterlyRows={data.capacityQuarterly}
        capacityYearlyRows={data.capacityYearly}
        year={year}
        demographicType={demographicType}
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
