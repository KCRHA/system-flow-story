import { useMemo, useState } from "react";
import KpiCard from "../KpiCard.jsx";
import InfoIcon from "../InfoIcon.jsx";
import QuarterPills from "../charts/QuarterPills.jsx";
import MonthPills from "../charts/MonthPills.jsx";
import FlowSankeyChart from "../charts/FlowSankeyChart.jsx";
import HomelessnessTrendChart from "../charts/HomelessnessTrendChart.jsx";
import FilterBar, { PopulationSegmentSelect, YearSelect, DemographicTypeSelect, DemographicCategorySelect, MeasureSelect, MEASURES } from "../FilterBar.jsx";
import { filterRows, distinctValues, resolveCell, INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";
import { quartersInYear, monthsInYear, monthsInQuarter, quarterStartOfMonth, buildFlowPeriod } from "../../lib/sankeyData.js";
import { subjectFor } from "../../lib/demographics.js";

// Plain-text definitions for every flow-type term shown in this section's
// KPI cards and sankey, for the section header's definitions popover —
// content supplied directly by the KCRHA team, not derived/guessed from the
// data pipeline. "Aged Out" is YYA-specific (see OutflowSection's own "Aged
// Out" KpiCard, which is likewise hidden for every other population
// segment).
// Split inflow/outflow, matching sankeyData.js's own INFLOW_REASONS/
// OUTFLOW_REASONS grouping — a horizontal rule separates the two groups in
// the popover (see definitionsContent) so "which side of the sankey is
// this term on" reads at a glance.
//
// Bodies here match KPI_CARD_INFO below word-for-word (minus each entry's
// own title, which is redundant with `term` in this list) — one glossary of
// plain-language definitions, shown two ways: all at once here, or one at a
// time next to its own KPI card.
const INFLOW_TERM_DEFINITIONS = [
  { term: "Newly experiencing homelessness", definition: "The person has no record of a prior experience of homelessness, or their last one ended more than 2 years ago." },
  { term: "Returned from housed", definition: "The person moved into housing after their last experience of homelessness, then became homeless again within 2 years." },
  { term: "Returned from inactive", definition: "The person's last experience of homelessness ended due to inactivity (30+ days with no recorded contact), and they became homeless again within 2 years." },
];
const OUTFLOW_TERM_DEFINITIONS = [
  { term: "Inactive", definition: "No qualifying activity recorded in HMIS for more than 30 days. This does not mean the person found housing." },
  { term: "Permanently housed", definition: "The person moved into permanent housing, based on their most recent activity in the system." },
  { term: "Deceased", definition: "The person passed away while experiencing homelessness." },
];
const AGED_OUT_DEFINITION = {
  term: "Aged Out",
  definition: "Individual turned 25 while experiencing homelessness and is no longer included in YYA reporting.",
};

// KCRHA methodology doc linked from every KPI-card popover's "See full
// definitions" (see KPI_CARD_INFO below) — the only definitions doc we
// have today, so every term points here for now; swap in per-term URLs
// later if/when more specific docs exist for the other terms. Hosted in
// public/docs so it ships with the site build (see BASE_URL below).
const FULL_DEFINITIONS_LINK = `${import.meta.env.BASE_URL}docs/KCRHA%20Active%20Homelessness%20Methodology.pdf`;

// Per-card hover definitions (see KpiCard's `info` prop) — same content as
// the INFLOW_/OUTFLOW_TERM_DEFINITIONS glossary above, just addressed by
// flow-type key instead of listed all at once, plus a `title` (shown bold
// in the popover) matching each card's own label.
const KPI_CARD_INFO = {
  experienced: {
    title: "Active in Our System",
    body: "Everyone with recorded activity indicating homelessness at some point during this period.",
    linkHref: FULL_DEFINITIONS_LINK,
  },
  newly_homeless: {
    title: "Newly Experiencing Homelessness",
    body: INFLOW_TERM_DEFINITIONS[0].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
  return_from_housed: {
    title: "Returned from Housed",
    body: INFLOW_TERM_DEFINITIONS[1].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
  return_from_inactive: {
    title: "Returned from Inactive",
    body: INFLOW_TERM_DEFINITIONS[2].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
  inactive: {
    title: "Inactive",
    body: OUTFLOW_TERM_DEFINITIONS[0].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
  permanently_housed: {
    title: "Permanently Housed",
    body: OUTFLOW_TERM_DEFINITIONS[1].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
  deceased: {
    title: "Deceased",
    body: OUTFLOW_TERM_DEFINITIONS[2].definition,
    linkHref: FULL_DEFINITIONS_LINK,
  },
};

// Short, always-visible line shown directly under each outflow card's label
// (see KpiCard's `description` prop) — distinct from KPI_CARD_INFO's longer
// hover definition above. Outflow-only, per the approved mockup: the inflow
// and hero cards don't carry one.
const KPI_CARD_DESCRIPTION = {
  inactive: "No activity for 30+ days, not confirmed housed",
  permanently_housed: "Moved into permanent housing",
  deceased: "Exit destination recorded as deceased",
};

// Same UTC-safe parsing as QuarterPills/ReturnCohortChart's quarterLabel —
// "YYYY-MM-DD" parses as UTC midnight, so reading it back with local-time
// getters can shift the quarter/year for anyone west of UTC.
function formatQuarterLabel(quarter) {
  const d = new Date(quarter);
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `Q${q} ${d.getUTCFullYear()}`;
}

// Same as formatQuarterLabel but without the year — for the "Months in Q2:"
// label above the scoped month-pills row, where the year is already shown
// elsewhere on screen.
function quarterAbbrevLabel(quarter) {
  return `Q${Math.floor(new Date(quarter).getUTCMonth() / 3) + 1}`;
}

function formatMonthLabel(month) {
  const d = new Date(month);
  return `${d.toLocaleString("en-US", { month: "long", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
}

// "up"/"down"/"flat" if `current` is (or must be) higher/lower/equal to
// `previous`; null if there's no previous period to compare against at all.
//
// Suppression only ever hides a NONZERO value below the threshold (see
// suppression.py) — a true zero is never suppressed. So a suppressed
// previous cell's real value is guaranteed to be in [1, threshold - 1],
// always > 0, even without knowing the exact number. A visible
// (marker-free) current value is therefore guaranteed higher than that
// ONLY if it's itself nonzero (which, being unsuppressed, means it's at
// or above the threshold); a visible current value of exactly 0 is below
// every possible hidden previous value, i.e. "down". The reverse (current
// suppressed) never needs handling here: KpiCard doesn't render an arrow
// next to a suppressed current value at all.
function trendDirectionFor(current, previous) {
  if (!current || !previous || current.marker) return null;
  if (previous.marker) return current.value > 0 ? "up" : "down";
  if (current.value > previous.value) return "up";
  if (current.value < previous.value) return "down";
  return "flat";
}

// Short, always-visible text for a KPI card's trend pill (see KpiCard's
// `trendText` prop) — covers every case trendDirectionFor above can produce
// an arrow for, condensed to pill length rather than a full sentence:
// - both sides known and different: an exact percent ("12% vs. Q1 2026").
// - both sides known and equal: called out as unchanged, not a 0% change.
// - a real (non-suppressed) previous value of 0: "New", no percent — percent
//   change from zero is undefined.
// - a suppressed previous value: no percent, naming that side as suppressed
//   rather than implying a precise number (the exact prior count isn't
//   knowable, only that it's under the suppression threshold — see
//   trendDirectionFor's comment on why direction alone is still safe to
//   state).
function trendPillText(current, previous, previousLabel) {
  if (!current || !previous || current.marker || !previousLabel) return null;
  if (previous.marker) return `vs. fewer than 11 in ${previousLabel}`;
  if (current.value === previous.value) return `No change vs. ${previousLabel}`;
  if (!previous.value) return `New vs. ${previousLabel}`;
  const percent = Math.round((Math.abs(current.value - previous.value) / previous.value) * 100);
  return `${percent}% vs. ${previousLabel}`;
}

// `cell`'s share of `total` ("12.3%"), for the inflow/outflow cards that
// show what fraction of everyone who experienced homelessness this period
// fell into that specific bucket. null whenever either side is suppressed
// (a ratio involving a hidden number isn't a real percentage — see
// suppression.py) or the total is zero (nothing to take a share of).
function percentOfExperienced(cell, total) {
  if (!cell || cell.marker || !total || total.marker || !total.value) return null;
  return `${Math.round((cell.value / total.value) * 100)}%`;
}

export default function OutflowSection({
  flowYearlyRows,
  flowQuarterlyRows,
  flowMonthlyRows,
  flowMonthlyLoading,
  populationSegment,
  onPopulationChange,
  years,
  year,
  onYearChange,
  demographicType,
  onDemographicTypeChange,
  demographicTypeOptions,
  demographicCategory,
  onDemographicCategoryChange,
  demographicCategoryOptions,
  filterDimension,
  filterCategory,
}) {
  const [selectedQuarter, setSelectedQuarter] = useState(null); // null = full year
  const [selectedMonth, setSelectedMonth] = useState(null); // null = no month pill active
  const [trendMeasure, setTrendMeasure] = useState(MEASURES[0].value); // which KPI the run chart below plots

  // Scoping to a demographic category isn't visible once a reader has
  // scrolled past the filter controls — same reasoning as LengthSection's
  // own blurb `subject` (see subjectFor) — so every piece of text here that
  // otherwise says plain "people" (this section's own header, the run
  // chart's heading/y-axis/hover panel) names who's actually being measured
  // instead.
  const subject = subjectFor(demographicType, demographicCategory);

  const scopedQuarterly = useMemo(
    () => filterRows(flowQuarterlyRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [flowQuarterlyRows, populationSegment, filterDimension, filterCategory]
  );
  const scopedMonthly = useMemo(
    () => filterRows(flowMonthlyRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [flowMonthlyRows, populationSegment, filterDimension, filterCategory]
  );
  const scopedYearly = useMemo(
    () =>
      flowYearlyRows.filter(
        (r) => r.population_segment === populationSegment && r.dimension === filterDimension && r.category === filterCategory
      ),
    [flowYearlyRows, populationSegment, filterDimension, filterCategory]
  );
  const allQuarters = useMemo(() => distinctValues(scopedQuarterly, "quarter").sort(), [scopedQuarterly]);
  const allMonths = useMemo(() => distinctValues(scopedMonthly, "month").sort(), [scopedMonthly]);
  const quartersForYear = useMemo(() => (year ? quartersInYear(scopedQuarterly, year) : []), [scopedQuarterly, year]);
  const monthsForYear = useMemo(() => (year ? monthsInYear(scopedMonthly, year) : []), [scopedMonthly, year]);
  // Every year in the Year dropdown that doesn't yet have all 4 quarters in
  // dashboard_flow_quarterly — labeled "(partial year)" there (see
  // YearSelect) so it reads the same as the Full year pill's own "(through
  // Aug)" suffix.
  const partialYears = useMemo(
    () => new Set(years.filter((y) => quartersInYear(scopedQuarterly, y).length < 4)),
    [years, scopedQuarterly]
  );
  // Falls back to Full Year (null) whenever selectedQuarter isn't valid for
  // the current population + year — either it belongs to a different year
  // (a year switch, which explicitly resets it below) or this population
  // segment simply has no data for it (rare, but a switch to a
  // shorter-history segment like YYA could hit this). Otherwise it carries
  // straight through a population switch unchanged, so browsing e.g. "Q2
  // 2026" for All Population and then switching to Veterans keeps showing
  // Q2 2026, not a reset to the full year. Same fallback for selectedMonth.
  const quarter =
    selectedQuarter && selectedQuarter.slice(0, 4) === String(year) && allQuarters.includes(selectedQuarter) ? selectedQuarter : null;
  const month = selectedMonth && selectedMonth.slice(0, 4) === String(year) && allMonths.includes(selectedMonth) ? selectedMonth : null;

  // Quarter and month pills are mutually exclusive: picking one always
  // clears the other (and "Full Year" — selectQuarter(null) — clears both),
  // so there's never a state where a quarter and a month are both active.
  const selectQuarter = (nextQuarter) => {
    setSelectedQuarter(nextQuarter);
    setSelectedMonth(null);
  };
  const selectMonth = (nextMonth) => {
    setSelectedMonth(nextMonth);
    setSelectedQuarter(null);
  };

  // The KPI cards and the sankey below are always the same period — one
  // piece of state (selectedYear/selectedQuarter/selectedMonth, via the
  // `year`/`quarter`/`month` fallbacks above) drives both, so it's never
  // possible to see e.g. Q2's cards next to Q3's chart. `month` takes
  // priority over `quarter` when resolving the period since the two are
  // kept mutually exclusive above (at most one is ever non-null).
  const period = useMemo(
    () =>
      year ? buildFlowPeriod(scopedYearly, scopedQuarterly, scopedMonthly, month ? { month } : quarter ? { quarter } : { year }) : null,
    [scopedYearly, scopedQuarterly, scopedMonthly, year, quarter, month]
  );

  // Each KPI card's trend arrow compares against the period immediately
  // before the one selected — the prior calendar quarter with a quarter
  // pill active, the prior calendar year in the full-year view. null (no
  // arrow) if that prior period falls outside the export window entirely
  // (e.g. the very first quarter/year of data), or — in the full-year view
  // — if the selected year itself isn't complete yet: dashboard_flow_quarterly
  // never carries an in-progress quarter (see build_flow_quarterly_rows), so
  // a year with fewer than all 4 of its quarters present is necessarily the
  // current, still-in-progress one. Comparing that partial year-to-date
  // total against a full prior year would always read as "down" regardless
  // of the real trend, so the comparison is skipped entirely rather than
  // shown misleadingly.
  const previousPeriod = useMemo(() => {
    if (!year) return null;
    if (month) {
      const idx = allMonths.indexOf(month);
      const prevMonth = idx > 0 ? allMonths[idx - 1] : null;
      return prevMonth ? buildFlowPeriod(scopedYearly, scopedQuarterly, scopedMonthly, { month: prevMonth }) : null;
    }
    if (quarter) {
      const idx = allQuarters.indexOf(quarter);
      const prevQuarter = idx > 0 ? allQuarters[idx - 1] : null;
      return prevQuarter ? buildFlowPeriod(scopedYearly, scopedQuarterly, scopedMonthly, { quarter: prevQuarter }) : null;
    }
    if (quartersForYear.length < 4) return null;
    return years.includes(year - 1) ? buildFlowPeriod(scopedYearly, scopedQuarterly, scopedMonthly, { year: year - 1 }) : null;
  }, [scopedYearly, scopedQuarterly, scopedMonthly, allQuarters, allMonths, years, year, quarter, month, quartersForYear]);

  // A human-readable label for whatever period previousPeriod above landed
  // on, for the KPI cards' trend-arrow tooltip ("...in Q1 2026") — mirrors
  // that same month/quarter/year-1 logic so the two never disagree about
  // which period they're describing.
  const previousPeriodLabel = useMemo(() => {
    if (!year) return null;
    if (month) {
      const idx = allMonths.indexOf(month);
      const prevMonth = idx > 0 ? allMonths[idx - 1] : null;
      return prevMonth ? formatMonthLabel(prevMonth) : null;
    }
    if (quarter) {
      const idx = allQuarters.indexOf(quarter);
      const prevQuarter = idx > 0 ? allQuarters[idx - 1] : null;
      return prevQuarter ? formatQuarterLabel(prevQuarter) : null;
    }
    if (quartersForYear.length < 4) return null;
    return years.includes(year - 1) ? String(year - 1) : null;
  }, [allQuarters, allMonths, years, year, quarter, month, quartersForYear]);

  // Population/year live in App.jsx now (shared across every section) — a
  // population switch there keeps browsing the same quarter/month here (see
  // the `quarter`/`month` fallbacks above, which just check the new prop
  // values); a year switch, though, should land back on the full-year view,
  // since "the same quarter" under a different year is a much bigger jump
  // than "the same quarter" under a different population. That reset falls
  // out of the same `quarter`/`month` derivations for free (selectedQuarter/
  // selectedMonth's year no longer matches the new `year` prop), so no extra
  // handler is needed for it.

  // The trend chart's own trailing (up to 3-year, 12-quarter) window always
  // ends at whatever's currently selected above: the exact quarter when a
  // quarter pill is active, the quarter containing the selected month when
  // a month pill is active, otherwise the most recent complete quarter
  // at-or-before the selected year (dashboard_flow_quarterly never carries
  // an in-progress quarter, so "at or before" is what lands on the latest
  // real one when the selected year isn't finished yet — same rule
  // CapacitySection's utilization chart follows for its own year-only
  // selector).
  const trendEndQuarter = useMemo(() => {
    let target;
    if (quarter) target = quarter;
    else if (month) {
      const d = new Date(month);
      target = new Date(Date.UTC(d.getUTCFullYear(), Math.floor(d.getUTCMonth() / 3) * 3, 1)).toISOString().slice(0, 10);
    } else {
      target = `${year}-12-31`;
    }
    return allQuarters.filter((q) => q <= target).at(-1) ?? null;
  }, [quarter, month, year, allQuarters]);
  // Pinned to the earliest 12 quarters we have (through end of 2023, given
  // data starting beginning-of-2021) whenever trendEndQuarter is too close
  // to the start of the dataset for a full trailing window — rather than
  // showing a short, growing chart for an early period, the window itself
  // stays fixed at 3 years and only the "selected period" ring (still
  // trendEndQuarter, passed to HomelessnessTrendChart unchanged below)
  // moves within it. Once trendEndQuarter is far enough in, this falls
  // back to the normal trailing window exactly as before.
  const trendQuarters = useMemo(() => {
    if (!trendEndQuarter) return [];
    const windowSize = 12;
    const idx = allQuarters.indexOf(trendEndQuarter);
    if (idx < windowSize - 1) return allQuarters.slice(0, windowSize);
    return allQuarters.slice(idx - (windowSize - 1), idx + 1);
  }, [allQuarters, trendEndQuarter]);
  // "Aged Out" is YYA-specific (see the "Aged Out" KpiCard's own gating
  // above) — hidden from the Measure dropdown for every other population
  // segment, same as the card itself.
  const trendMeasureOptions = useMemo(() => MEASURES.filter((m) => !m.yyaOnly || populationSegment === "yya"), [populationSegment]);
  const activeTrendMeasure = trendMeasureOptions.find((m) => m.value === trendMeasure) ?? trendMeasureOptions[0];
  const trendPoints = useMemo(
    () =>
      trendQuarters.map((q) => ({
        quarter: q,
        ...resolveCell(
          scopedQuarterly.find((r) => r.quarter === q && r.flow_type === activeTrendMeasure.value),
          "count"
        ),
      })),
    [trendQuarters, scopedQuarterly, activeTrendMeasure]
  );

  // Race/ethnicity is HMIS's one multi-select demographic field — a person
  // can be counted under more than one category at once (e.g. Black AND
  // Hispanic/Latina/o both show them as "Included"), unlike every other
  // demographic type here, where a person falls into exactly one category.
  // That's easy to misread as a data error (category totals can add up to
  // more than the overall total), so it's called out explicitly whenever
  // this type is selected, not just when a specific category is — as an
  // InfoIcon next to the Category filter (see DemographicCategorySelect's
  // `info` prop) rather than an always-visible paragraph, so it doesn't
  // clutter the default "All" view. null whenever the current demographic
  // type needs no clarification, which also hides the icon entirely (see
  // FilterBar.jsx's DemographicCategorySelect).
  const demographicNote =
    demographicType === "race_ethnicity" ? (
      <p>
        In HMIS, individuals can select more than one race or ethnicity. For the most complete picture, this filter
        includes everyone who selected a given category, whether alone or in combination with another.
      </p>
    ) : (
      // Project type engagement categories can also overlap (someone can be
      // engaged with Street Outreach and Emergency Shelter in the same
      // period), same reasoning as the race/ethnicity note above, plus a
      // second thing worth calling out: "engaged" counts anyone whose
      // enrollment overlaps any part of the selected period, not just
      // enrollments still open at the period's end.
      demographicType === "project_type_engagement" && (
        <p>
          A person can be engaged with more than one project type in the same period, so category totals can add up
          to more than the overall total. "Engaged" includes anyone with an enrollment overlapping any part of the
          selected period, not just enrollments still open at the end of it.
        </p>
      )
    );

  // The definitions popover's content (see the section header's InfoIcon) —
  // flow-term glossary, split into an inflow group and an outflow group
  // (divided by a rule, matching the sankey's own left/right columns), with
  // "Aged Out" appended to the outflow group only for the YYA population
  // segment, same gating as the "Aged Out" KpiCard itself further down.
  const definitionsContent = (
    <>
      <dl className="definitions-list">
        {INFLOW_TERM_DEFINITIONS.map(({ term, definition }) => (
          <div className="definitions-item" key={term}>
            <dt>{term}</dt>
            <dd>{definition}</dd>
          </div>
        ))}
      </dl>
      <hr className="definitions-divider" />
      <dl className="definitions-list">
        {[...OUTFLOW_TERM_DEFINITIONS, ...(populationSegment === "yya" ? [AGED_OUT_DEFINITION] : [])].map(({ term, definition }) => (
          <div className="definitions-item" key={term}>
            <dt>{term}</dt>
            <dd>{definition}</dd>
          </div>
        ))}
      </dl>
    </>
  );

  // Months not covered by any complete quarter (dashboard_flow_quarterly
  // never carries one still in progress — see quartersInYear's own
  // comment) — the trailing partial-quarter months of the current year
  // (e.g. July/August before Q3 is complete), just for naming the "Full
  // year (through Aug)" pill below.
  const trailingMonths = useMemo(
    () => monthsForYear.filter((m) => !quartersForYear.includes(quarterStartOfMonth(m))),
    [monthsForYear, quartersForYear]
  );
  // "Aug" suffix for the "Full Year (through Aug)" pill label — only once
  // the selected year isn't complete yet (same quartersForYear.length < 4
  // signal previousPeriod/the chart-note caveat elsewhere in this file use)
  // and there's actually a trailing month to name.
  const throughLabel = useMemo(() => {
    if (quartersForYear.length >= 4 || trailingMonths.length === 0) return null;
    return new Date(trailingMonths.at(-1)).toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  }, [quartersForYear, trailingMonths]);

  // Month pills always mirror whatever's selected on the left: that
  // quarter's 3 months when a quarter pill is active, every month in the
  // year otherwise (Full Year, or a specific month picked directly — which
  // clears `quarter` per the mutual-exclusivity handling above, but doesn't
  // correspond to any one quarter pill either, so the full year's months
  // stay the relevant set to keep browsing from).
  const monthsForQuarter = useMemo(() => monthsInQuarter(scopedMonthly, quarter), [scopedMonthly, quarter]);
  const activeMonths = quarter ? monthsForQuarter : monthsForYear;

  if (!period) {
    return (
      <section className="section">
        <div className="section-header">
          <div>
            <h2 className="section-heading">How are {subject} experiencing homelessness coming into our system, and where are they going?</h2>
            <p className="section-subhead">Pick a year, then a quarter or month.</p>
          </div>
          <InfoIcon label="Show definitions" size="lg" align="end">
            {definitionsContent}
          </InfoIcon>
        </div>
        <FilterBar>
          <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
          <YearSelect years={years} value={year} onChange={onYearChange} partialYears={partialYears} />
          <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} options={demographicTypeOptions} />
          <DemographicCategorySelect
            options={demographicCategoryOptions}
            value={demographicCategory}
            onChange={onDemographicCategoryChange}
            disabled={demographicType === "overall"}
            info={demographicNote && <InfoIcon label="About this category" align="end">{demographicNote}</InfoIcon>}
          />
        </FilterBar>
        <p className="suppressed-note">No data available for this population.</p>
      </section>
    );
  }

  const periodLabel = month ? formatMonthLabel(month) : quarter ? formatQuarterLabel(quarter) : String(year);
  // The hero card's own total, not a snapshot: everyone who experienced
  // homelessness at any point during the period — a true distinct-person
  // count sourced from the pipeline (see buildFlowPeriod), not derived
  // here, so a person with multiple episodes in the same period (e.g.
  // newly homeless in February, returns from housed in October) is only
  // counted once.
  const totalExperienced = period.experiencedHomelessness;
  const previousTotalExperienced = previousPeriod?.experiencedHomelessness ?? null;
  // Set together, for every flow_type, whenever this exact (period,
  // population, dimension, category) combination was too small to safely
  // break down at all (see suppression.py's
  // apply_insufficient_population_fallback) — checking one representative
  // cell is enough to know the whole period is affected.
  const insufficientPopulation = totalExperienced.marker === INSUFFICIENT_POPULATION_MARKER;

  return (
    <section className="section">
      <div className="section-header">
        <div>
          <h2 className="section-heading">How are {subject} experiencing homelessness coming into our system, and where are they going?</h2>
          <p className="section-subhead">Pick a year, then a quarter or month.</p>
        </div>
        <InfoIcon label="Show definitions" size="lg" align="end">
          {definitionsContent}
        </InfoIcon>
      </div>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
        <YearSelect years={years} value={year} onChange={onYearChange} partialYears={partialYears} />
        <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} options={demographicTypeOptions} />
        <DemographicCategorySelect
          options={demographicCategoryOptions}
          value={demographicCategory}
          onChange={onDemographicCategoryChange}
          disabled={demographicType === "overall"}
          info={demographicNote && <InfoIcon label="About this category" align="end">{demographicNote}</InfoIcon>}
        />
      </FilterBar>
      <div className="kpi-row-month">
        <span>{periodLabel}</span>
        {previousPeriodLabel && (
          <div className="arrow-legend">
            <span>Arrows compare to {previousPeriodLabel}:</span>
            <span className="legend-chip positive">Positive change</span>
            <span className="legend-chip concerning">Concerning change</span>
            <span className="legend-chip neutral">Neutral</span>
          </div>
        )}
      </div>
      <div className="period-pills-row">
        <QuarterPills
          quarters={quartersForYear}
          selected={quarter}
          fullYearActive={!quarter && !month}
          onSelect={selectQuarter}
          throughLabel={throughLabel}
        />
        {flowMonthlyLoading && monthsForYear.length === 0 ? (
          <p className="month-pills-loading">Loading months…</p>
        ) : (
          activeMonths.length > 0 && (
            <>
              <span className="period-pills-divider" aria-hidden="true" />
              <div className="month-pills-group">
                {quarter && <span className="month-pills-label">Months in {quarterAbbrevLabel(quarter)}:</span>}
                <MonthPills months={activeMonths} selected={month} onSelect={selectMonth} />
              </div>
            </>
          )
        )}
      </div>
      {insufficientPopulation ? (
        <p className="suppressed-note">
          Population too small to safely display for this combination of population, demographic, and period. Try a
          different category, population, or period.
        </p>
      ) : (
        <>
          <div className="kpi-rows">
            <div className="kpi-row kpi-row-hero">
              <KpiCard
                label={`Active in our system at any point in ${periodLabel}`}
                value={totalExperienced.value?.toLocaleString()}
                marker={totalExperienced.marker}
                trendDirection={trendDirectionFor(totalExperienced, previousTotalExperienced)}
                trendText={trendPillText(totalExperienced, previousTotalExperienced, previousPeriodLabel)}
                goodDirection="down"
                info={KPI_CARD_INFO.experienced}
              />
            </div>
            <h3 className="kpi-group-heading">Entered the system in {periodLabel}</h3>
            <div className="kpi-row">
              <KpiCard
                label="Newly experiencing homelessness"
                value={period.inflow.newly_homeless.value?.toLocaleString()}
                marker={period.inflow.newly_homeless.marker}
                percent={percentOfExperienced(period.inflow.newly_homeless, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.newly_homeless, previousPeriod?.inflow?.newly_homeless)}
                trendText={trendPillText(period.inflow.newly_homeless, previousPeriod?.inflow?.newly_homeless, previousPeriodLabel)}
                goodDirection="down"
                info={KPI_CARD_INFO.newly_homeless}
              />
              <KpiCard
                label="Returned from housed"
                value={period.inflow.return_from_housed.value?.toLocaleString()}
                marker={period.inflow.return_from_housed.marker}
                percent={percentOfExperienced(period.inflow.return_from_housed, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_housed, previousPeriod?.inflow?.return_from_housed)}
                trendText={trendPillText(period.inflow.return_from_housed, previousPeriod?.inflow?.return_from_housed, previousPeriodLabel)}
                goodDirection="down"
                info={KPI_CARD_INFO.return_from_housed}
              />
              <KpiCard
                label="Returned from inactive"
                value={period.inflow.return_from_inactive.value?.toLocaleString()}
                marker={period.inflow.return_from_inactive.marker}
                percent={percentOfExperienced(period.inflow.return_from_inactive, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_inactive, previousPeriod?.inflow?.return_from_inactive)}
                trendText={trendPillText(period.inflow.return_from_inactive, previousPeriod?.inflow?.return_from_inactive, previousPeriodLabel)}
                goodDirection="down"
                info={KPI_CARD_INFO.return_from_inactive}
              />
            </div>
            <h3 className="kpi-group-heading">Exited the system in {periodLabel}</h3>
            <div className="kpi-row">
              <KpiCard
                label="Inactive"
                value={period.outflow.inactive.value?.toLocaleString()}
                marker={period.outflow.inactive.marker}
                percent={percentOfExperienced(period.outflow.inactive, totalExperienced)}
                description={KPI_CARD_DESCRIPTION.inactive}
                trendDirection={trendDirectionFor(period.outflow.inactive, previousPeriod?.outflow?.inactive)}
                trendText={trendPillText(period.outflow.inactive, previousPeriod?.outflow?.inactive, previousPeriodLabel)}
                goodDirection={null}
                info={KPI_CARD_INFO.inactive}
              />
              <KpiCard
                label="Permanently housed"
                value={period.outflow.permanently_housed.value?.toLocaleString()}
                marker={period.outflow.permanently_housed.marker}
                percent={percentOfExperienced(period.outflow.permanently_housed, totalExperienced)}
                description={KPI_CARD_DESCRIPTION.permanently_housed}
                trendDirection={trendDirectionFor(period.outflow.permanently_housed, previousPeriod?.outflow?.permanently_housed)}
                trendText={trendPillText(period.outflow.permanently_housed, previousPeriod?.outflow?.permanently_housed, previousPeriodLabel)}
                goodDirection="up"
                info={KPI_CARD_INFO.permanently_housed}
              />
              <KpiCard
                label="Deceased"
                value={period.outflow.deceased.value?.toLocaleString()}
                marker={period.outflow.deceased.marker}
                percent={percentOfExperienced(period.outflow.deceased, totalExperienced)}
                description={KPI_CARD_DESCRIPTION.deceased}
                trendDirection={trendDirectionFor(period.outflow.deceased, previousPeriod?.outflow?.deceased)}
                trendText={trendPillText(period.outflow.deceased, previousPeriod?.outflow?.deceased, previousPeriodLabel)}
                goodDirection={null}
                info={KPI_CARD_INFO.deceased}
              />
              {/* Only meaningful for the YYA population — every other segment's
                  aged_out count is always 0 (see build_flow.py's
                  _partition_by_individual), so the card is hidden rather than
                  shown as a perpetual zero. */}
              {populationSegment === "yya" && (
                <KpiCard
                  label="Aged Out"
                  value={period.outflow.aged_out.value?.toLocaleString()}
                  marker={period.outflow.aged_out.marker}
                  trendDirection={trendDirectionFor(period.outflow.aged_out, previousPeriod?.outflow?.aged_out)}
                  trendText={trendPillText(period.outflow.aged_out, previousPeriod?.outflow?.aged_out, previousPeriodLabel)}
                  goodDirection={null}
                />
              )}
            </div>
          </div>
          {/* Only meaningful in the full-year view of the current, still-in-progress
              year (same "fewer than 4 quarters present" signal previousPeriod above
              uses) — a quarter/month pill, or a completed prior year, already reflects
              its own full selected period, so the caveat would be noise there. */}
          {!quarter && !month && quartersForYear.length < 4 && (
            <p className="partial-year-note">
              Current-year totals don't reflect a full year of data yet, so they're expected to be lower than
              completed years.
            </p>
          )}
          <h3 className="kpi-group-heading">What this shows</h3>
          <p className="chart-analysis">
            This view shows movement across a whole period, including who entered our system, who was active, and
            who exited. A total that looks stable from one period to the next can hide a lot of change, with many
            people entering and exiting at the same time. The entry cards show how many people are newly
            experiencing homelessness and how many are returning, and the exit cards show how many people left the
            system.
          </p>
          {/* Methodology page doesn't exist yet — placeholder so the link doesn't
              navigate away until it's built. */}
          <a href="#" className="methodology-link" onClick={(e) => e.preventDefault()}>
            Learn more about our methodology and definitions
          </a>
          <hr className="definitions-divider" />
          {trendPoints.length > 0 && (
            <>
              <h2 className="section-heading">
                How has the number of {subject} {activeTrendMeasure.axisLabel} changed over time?
              </h2>
              <p className="section-subhead">Choose a measure to see its trend. Hover over a point for details.</p>
              <FilterBar>
                <MeasureSelect value={activeTrendMeasure.value} onChange={setTrendMeasure} options={trendMeasureOptions} />
                <span className="trend-sync-chip">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  By quarter, following your {periodLabel} selection and filters above
                </span>
              </FilterBar>
              <div className="chart-frame-box">
                <p className="chart-frame-label">By quarter</p>
                <HomelessnessTrendChart
                  points={trendPoints}
                  measureLabel={activeTrendMeasure.label}
                  unitLabel={activeTrendMeasure.unitLabel}
                  axisLabel={activeTrendMeasure.axisLabel}
                  subject={subject}
                  selectedQuarter={trendEndQuarter}
                />
              </div>
              <h3 className="kpi-group-heading">What this shows</h3>
              <p className="chart-analysis">
                Looking across periods shows whether a change is part of a longer pattern or a one-time shift. The
                median gives a steady reference point, so a period well above or below it stands out. Some measures
                may rise and fall with the seasons, so comparing the same quarter across years can tell you more
                than comparing back-to-back quarters.
              </p>
              <hr className="definitions-divider" />
            </>
          )}
          <h2 className="section-heading">How did people's status change from the start to the end of the period?</h2>
          <p className="section-subhead">Each band shows the number of people who moved from one status to another.</p>
          <FlowSankeyChart data={period} periodLabel={periodLabel} isFullYear={!quarter && !month} populationSegment={populationSegment} />
          <h3 className="kpi-group-heading">What this shows</h3>
          <p className="chart-analysis" style={{ marginBottom: 0 }}>
            Each person appears once on each side of the chart, based on their status at the start and end of the
            period. Following a band from left to right shows where people who started in each group ended up. For
            example, compare how many people newly experiencing homelessness ended the period permanently housed,
            still active, or with an unknown status.
          </p>
        </>
      )}
    </section>
  );
}
