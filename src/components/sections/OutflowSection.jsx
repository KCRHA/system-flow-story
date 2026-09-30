import { useMemo, useState } from "react";
import KpiCard from "../KpiCard.jsx";
import QuarterPills from "../charts/QuarterPills.jsx";
import MonthPills from "../charts/MonthPills.jsx";
import FlowSankeyChart from "../charts/FlowSankeyChart.jsx";
import HomelessnessTrendChart from "../charts/HomelessnessTrendChart.jsx";
import FilterBar, { PopulationSegmentSelect, YearSelect, DemographicTypeSelect, DemographicCategorySelect } from "../FilterBar.jsx";
import { filterRows, distinctValues, resolveCell, INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";
import { quartersInYear, monthsInYear, buildFlowPeriod } from "../../lib/sankeyData.js";

// Same UTC-safe parsing as QuarterPills/ReturnCohortChart's quarterLabel —
// "YYYY-MM-DD" parses as UTC midnight, so reading it back with local-time
// getters can shift the quarter/year for anyone west of UTC.
function formatQuarterLabel(quarter) {
  const d = new Date(quarter);
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `Q${q} ${d.getUTCFullYear()}`;
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

// A hover sentence for a KPI card's trend arrow, covering every case
// trendDirectionFor above can produce an arrow for:
// - both sides known and different: an exact percent ("This is a 12%
//   increase from 8,404 in Q1 2026.").
// - both sides known and equal: called out as unchanged, not a 0% change.
// - a real (non-suppressed) previous value of 0: direction only, no percent
//   — percent change from zero is undefined.
// - a suppressed previous value: direction only, naming that side as
//   suppressed rather than implying a precise number (the exact prior
//   count isn't knowable, only that it's under the suppression threshold —
//   see trendDirectionFor's comment on why direction alone is still safe
//   to state).
function trendTooltipFor(current, previous, previousLabel) {
  if (!current || !previous || current.marker || !previousLabel) return null;
  if (previous.marker) {
    return current.value > 0
      ? `This is an increase from fewer than 11 in ${previousLabel}.`
      : `This is a decrease from fewer than 11 in ${previousLabel}.`;
  }
  if (current.value === previous.value) {
    return `This is unchanged from ${previous.value.toLocaleString()} in ${previousLabel}.`;
  }
  if (!previous.value) {
    return `This is an increase from 0 in ${previousLabel}.`;
  }
  const direction = current.value > previous.value ? "increase" : "decrease";
  const percent = Math.round((Math.abs(current.value - previous.value) / previous.value) * 100);
  return `This is a ${percent}% ${direction} from ${previous.value.toLocaleString()} in ${previousLabel}.`;
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
  const quarterIdx = quarter ? allQuarters.indexOf(quarter) : -1;
  const stepQuarter = (delta) => {
    const nextIdx = quarterIdx + delta;
    if (nextIdx < 0 || nextIdx >= allQuarters.length) return;
    const nextQuarter = allQuarters[nextIdx];
    selectQuarter(nextQuarter);
    // Stepping past a year boundary (e.g. Q1 -> prior Q4) needs to move
    // the *shared* year selector too, not just the local quarter — React
    // batches this with the selectQuarter above, so there's no in-between
    // render where they disagree.
    const nextYear = Number(nextQuarter.slice(0, 4));
    if (nextYear !== year) onYearChange(nextYear);
  };

  const monthIdx = month ? allMonths.indexOf(month) : -1;
  const stepMonth = (delta) => {
    const nextIdx = monthIdx + delta;
    if (nextIdx < 0 || nextIdx >= allMonths.length) return;
    const nextMonth = allMonths[nextIdx];
    selectMonth(nextMonth);
    const nextYear = Number(nextMonth.slice(0, 4));
    if (nextYear !== year) onYearChange(nextYear);
  };

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
  const trendQuarters = useMemo(() => {
    if (!trendEndQuarter) return [];
    const idx = allQuarters.indexOf(trendEndQuarter);
    return allQuarters.slice(Math.max(0, idx - 11), idx + 1);
  }, [allQuarters, trendEndQuarter]);
  const trendPoints = useMemo(
    () =>
      trendQuarters.map((q) => ({
        quarter: q,
        ...resolveCell(
          scopedQuarterly.find((r) => r.quarter === q && r.flow_type === "experienced_homelessness"),
          "count"
        ),
      })),
    [trendQuarters, scopedQuarterly]
  );

  // Race/ethnicity is HMIS's one multi-select demographic field — a person
  // can be counted under more than one category at once (e.g. Black AND
  // Hispanic/Latina/o both show them as "Included"), unlike every other
  // demographic type here, where a person falls into exactly one category.
  // That's easy to misread as a data error (category totals can add up to
  // more than the overall total), so it's called out explicitly whenever
  // this type is selected, not just when a specific category is.
  const demographicNote =
    demographicType === "race_ethnicity" ? (
      <p className="demographic-note">
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
        <p className="demographic-note">
          A person can be engaged with more than one project type in the same period, so category totals can add up
          to more than the overall total. "Engaged" includes anyone with an enrollment overlapping any part of the
          selected period, not just enrollments still open at the end of it.
        </p>
      )
    );

  if (!period) {
    return (
      <section className="section">
        <h2 className="section-heading">Entries, Actively Experiencing Homelessness &amp; Exits</h2>
        <p className="section-subhead">
          How many people are entering, staying active in, and leaving our homelessness response system? Pick a
          year, then click a quarter or a month to zoom into it.
        </p>
        <FilterBar>
          <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
          <YearSelect years={years} value={year} onChange={onYearChange} />
          <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} options={demographicTypeOptions} />
          <DemographicCategorySelect
            options={demographicCategoryOptions}
            value={demographicCategory}
            onChange={onDemographicCategoryChange}
            disabled={demographicType === "overall"}
          />
        </FilterBar>
        {demographicNote}
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
      <h2 className="section-heading">Entries, Actively Experiencing Homelessness &amp; Exits</h2>
      <p className="section-subhead">
        How many people are entering, staying active in, and leaving our homelessness response system? Pick a year,
        then click a quarter or a month to zoom into it: the cards and chart below always show the same period.
      </p>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
        <YearSelect years={years} value={year} onChange={onYearChange} />
        <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} options={demographicTypeOptions} />
        <DemographicCategorySelect
          options={demographicCategoryOptions}
          value={demographicCategory}
          onChange={onDemographicCategoryChange}
          disabled={demographicType === "overall"}
        />
      </FilterBar>
      {demographicNote}
      <div className="kpi-row-month">
        <span>{periodLabel}</span>
        <div className="kpi-month-nav">
          <button
            type="button"
            aria-label={month ? "Show an older month" : "Show an older quarter"}
            disabled={month ? monthIdx <= 0 : !quarter || quarterIdx <= 0}
            onClick={() => (month ? stepMonth(-1) : stepQuarter(-1))}
          >
            ‹
          </button>
          <button
            type="button"
            aria-label={month ? "Show a more recent month" : "Show a more recent quarter"}
            disabled={month ? monthIdx >= allMonths.length - 1 : !quarter || quarterIdx >= allQuarters.length - 1}
            onClick={() => (month ? stepMonth(1) : stepQuarter(1))}
          >
            ›
          </button>
        </div>
      </div>
      <QuarterPills quarters={quartersForYear} selected={quarter} fullYearActive={!quarter && !month} onSelect={selectQuarter} />
      {flowMonthlyLoading && monthsForYear.length === 0 ? (
        <p className="month-pills-loading">Loading months…</p>
      ) : (
        <MonthPills months={monthsForYear} selected={month} onSelect={selectMonth} />
      )}
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
                label={`Experienced Homelessness At Any Point In ${periodLabel}`}
                value={totalExperienced.value?.toLocaleString()}
                marker={totalExperienced.marker}
                trendDirection={trendDirectionFor(totalExperienced, previousTotalExperienced)}
                trendTooltip={trendTooltipFor(totalExperienced, previousTotalExperienced, previousPeriodLabel)}
                goodDirection="down"
              />
            </div>
            <div className="kpi-row">
              <KpiCard
                label="Newly Homeless"
                value={period.inflow.newly_homeless.value?.toLocaleString()}
                marker={period.inflow.newly_homeless.marker}
                percent={percentOfExperienced(period.inflow.newly_homeless, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.newly_homeless, previousPeriod?.inflow?.newly_homeless)}
                trendTooltip={trendTooltipFor(period.inflow.newly_homeless, previousPeriod?.inflow?.newly_homeless, previousPeriodLabel)}
                goodDirection="down"
              />
              <KpiCard
                label="Return from Housed"
                value={period.inflow.return_from_housed.value?.toLocaleString()}
                marker={period.inflow.return_from_housed.marker}
                percent={percentOfExperienced(period.inflow.return_from_housed, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_housed, previousPeriod?.inflow?.return_from_housed)}
                trendTooltip={trendTooltipFor(period.inflow.return_from_housed, previousPeriod?.inflow?.return_from_housed, previousPeriodLabel)}
                goodDirection="down"
              />
              <KpiCard
                label="Return from Inactive"
                value={period.inflow.return_from_inactive.value?.toLocaleString()}
                marker={period.inflow.return_from_inactive.marker}
                percent={percentOfExperienced(period.inflow.return_from_inactive, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_inactive, previousPeriod?.inflow?.return_from_inactive)}
                trendTooltip={trendTooltipFor(period.inflow.return_from_inactive, previousPeriod?.inflow?.return_from_inactive, previousPeriodLabel)}
                goodDirection="down"
              />
            </div>
            <div className="kpi-row">
              <KpiCard
                label="Inactive"
                value={period.outflow.inactive.value?.toLocaleString()}
                marker={period.outflow.inactive.marker}
                percent={percentOfExperienced(period.outflow.inactive, totalExperienced)}
                trendDirection={trendDirectionFor(period.outflow.inactive, previousPeriod?.outflow?.inactive)}
                trendTooltip={trendTooltipFor(period.outflow.inactive, previousPeriod?.outflow?.inactive, previousPeriodLabel)}
                goodDirection={null}
              />
              <KpiCard
                label="Permanently Housed"
                value={period.outflow.permanently_housed.value?.toLocaleString()}
                marker={period.outflow.permanently_housed.marker}
                percent={percentOfExperienced(period.outflow.permanently_housed, totalExperienced)}
                trendDirection={trendDirectionFor(period.outflow.permanently_housed, previousPeriod?.outflow?.permanently_housed)}
                trendTooltip={trendTooltipFor(period.outflow.permanently_housed, previousPeriod?.outflow?.permanently_housed, previousPeriodLabel)}
                goodDirection="up"
              />
              <KpiCard
                label="Deceased"
                value={period.outflow.deceased.value?.toLocaleString()}
                marker={period.outflow.deceased.marker}
                percent={percentOfExperienced(period.outflow.deceased, totalExperienced)}
                trendDirection={trendDirectionFor(period.outflow.deceased, previousPeriod?.outflow?.deceased)}
                trendTooltip={trendTooltipFor(period.outflow.deceased, previousPeriod?.outflow?.deceased, previousPeriodLabel)}
                goodDirection={null}
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
                  trendTooltip={trendTooltipFor(period.outflow.aged_out, previousPeriod?.outflow?.aged_out, previousPeriodLabel)}
                  goodDirection={null}
                />
              )}
            </div>
          </div>
          <ul className="chart-note">
            <li>The dashboard counts everyone who was active at least once during the selected period.</li>
            {/* Only meaningful in the full-year view of the current, still-in-progress
                year (same "fewer than 4 quarters present" signal previousPeriod above
                uses) — a quarter/month pill, or a completed prior year, already reflects
                its own full selected period, so the caveat would be noise there. */}
            {!quarter && !month && quartersForYear.length < 4 && (
              <li>Current-year totals don't reflect a full year of data yet, so they're expected to be lower than completed years.</li>
            )}
          </ul>
          <p className="chart-analysis">
            The number of people experiencing homelessness has <strong>stayed fairly consistent year to year</strong>
            , which can point to sustained high demand for programs, with program capacity holding fairly steady
            alongside it.
          </p>
          {trendPoints.length > 0 && (
            <>
              <p className="section-subhead">
                Time periods above the median of the displayed points are shaded navy; time periods below are shaded
                light green.
              </p>
              <HomelessnessTrendChart points={trendPoints} />
            </>
          )}
          <p className="section-subhead">
            The ribbon chart below shows how people's homelessness status changes between the start and end of the
            selected period. The left column is how each person's episode began this period (already active, newly
            homeless, or returning from housed or inactive); the right column is how it ended (still active,
            permanently housed, inactive, or deceased). Each ribbon connects one starting status to one ending
            status, and its width is the number of people who took that specific path: hover over a ribbon to see
            the number of people included. For example, a wide ribbon from "Newly Homeless" to "Still Active" means
            most people who newly became homeless this period were still experiencing homelessness by its end,
            while a thinner ribbon from "Newly Homeless" to "Permanently Housed" means only a small share of that
            same group exited to housing within the period.
          </p>
          <FlowSankeyChart data={period} periodLabel={periodLabel} isFullYear={!quarter && !month} populationSegment={populationSegment} />
        </>
      )}
    </section>
  );
}
