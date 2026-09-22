import { useMemo, useState } from "react";
import KpiCard from "../KpiCard.jsx";
import QuarterPills from "../charts/QuarterPills.jsx";
import FlowSankeyChart from "../charts/FlowSankeyChart.jsx";
import FilterBar, { PopulationSegmentSelect, YearSelect, DemographicTypeSelect, DemographicCategorySelect } from "../FilterBar.jsx";
import { filterRows, distinctValues, INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";
import { quartersInYear, buildFlowPeriod } from "../../lib/sankeyData.js";

// Same UTC-safe parsing as QuarterPills/ReturnCohortChart's quarterLabel —
// "YYYY-MM-DD" parses as UTC midnight, so reading it back with local-time
// getters can shift the quarter/year for anyone west of UTC.
function formatQuarterLabel(quarter) {
  const d = new Date(quarter);
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `Q${q} ${d.getUTCFullYear()}`;
}

// "up"/"down" if `current` is (or must be) higher/lower than `previous`;
// null if there's no previous period to compare against, or we genuinely
// can't tell.
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
  return null;
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
  populationSegment,
  onPopulationChange,
  years,
  year,
  onYearChange,
  demographicType,
  onDemographicTypeChange,
  demographicCategory,
  onDemographicCategoryChange,
  demographicCategoryOptions,
  filterDimension,
  filterCategory,
}) {
  const [selectedQuarter, setSelectedQuarter] = useState(null); // null = full year

  const scopedQuarterly = useMemo(
    () => filterRows(flowQuarterlyRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [flowQuarterlyRows, populationSegment, filterDimension, filterCategory]
  );
  const scopedYearly = useMemo(
    () =>
      flowYearlyRows.filter(
        (r) => r.population_segment === populationSegment && r.dimension === filterDimension && r.category === filterCategory
      ),
    [flowYearlyRows, populationSegment, filterDimension, filterCategory]
  );
  const allQuarters = useMemo(() => distinctValues(scopedQuarterly, "quarter").sort(), [scopedQuarterly]);
  const quartersForYear = useMemo(() => (year ? quartersInYear(scopedQuarterly, year) : []), [scopedQuarterly, year]);
  // Falls back to Full Year (null) whenever selectedQuarter isn't valid for
  // the current population + year — either it belongs to a different year
  // (a year switch, which explicitly resets it below) or this population
  // segment simply has no data for it (rare, but a switch to a
  // shorter-history segment like YYA could hit this). Otherwise it carries
  // straight through a population switch unchanged, so browsing e.g. "Q2
  // 2026" for All Population and then switching to Veterans keeps showing
  // Q2 2026, not a reset to the full year.
  const quarter =
    selectedQuarter && selectedQuarter.slice(0, 4) === String(year) && allQuarters.includes(selectedQuarter) ? selectedQuarter : null;

  // The KPI cards and the sankey below are always the same period — one
  // piece of state (selectedYear/selectedQuarter, via the `year`/`quarter`
  // fallbacks above) drives both, so it's never possible to see e.g. Q2's
  // cards next to Q3's chart.
  const period = useMemo(
    () => (year ? buildFlowPeriod(scopedYearly, scopedQuarterly, quarter ? { quarter } : { year }) : null),
    [scopedYearly, scopedQuarterly, year, quarter]
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
    if (quarter) {
      const idx = allQuarters.indexOf(quarter);
      const prevQuarter = idx > 0 ? allQuarters[idx - 1] : null;
      return prevQuarter ? buildFlowPeriod(scopedYearly, scopedQuarterly, { quarter: prevQuarter }) : null;
    }
    if (quartersForYear.length < 4) return null;
    return years.includes(year - 1) ? buildFlowPeriod(scopedYearly, scopedQuarterly, { year: year - 1 }) : null;
  }, [scopedYearly, scopedQuarterly, allQuarters, years, year, quarter, quartersForYear]);

  // Population/year live in App.jsx now (shared across every section) — a
  // population switch there keeps browsing the same quarter here (see the
  // `quarter` fallback above, which just checks the new prop values); a
  // year switch, though, should land back on the full-year view, since
  // "the same quarter" under a different year is a much bigger jump than
  // "the same quarter" under a different population. That reset falls out
  // of the same `quarter` derivation for free (selectedQuarter's year no
  // longer matches the new `year` prop), so no extra handler is needed for
  // it.
  const quarterIdx = quarter ? allQuarters.indexOf(quarter) : -1;
  const stepQuarter = (delta) => {
    const nextIdx = quarterIdx + delta;
    if (nextIdx < 0 || nextIdx >= allQuarters.length) return;
    const nextQuarter = allQuarters[nextIdx];
    setSelectedQuarter(nextQuarter);
    // Stepping past a year boundary (e.g. Q1 -> prior Q4) needs to move
    // the *shared* year selector too, not just the local quarter — React
    // batches this with the setSelectedQuarter above, so there's no
    // in-between render where they disagree.
    const nextYear = Number(nextQuarter.slice(0, 4));
    if (nextYear !== year) onYearChange(nextYear);
  };

  // Race/ethnicity is HMIS's one multi-select demographic field — a person
  // can be counted under more than one category at once (e.g. Black AND
  // Hispanic/Latina/o both show them as "Included"), unlike every other
  // demographic type here, where a person falls into exactly one category.
  // That's easy to misread as a data error (category totals can add up to
  // more than the overall total), so it's called out explicitly whenever
  // this type is selected, not just when a specific category is.
  const demographicNote = demographicType === "race_ethnicity" && (
    <p className="demographic-note">
      In HMIS, individuals can select more than one race or ethnicity. For the most complete picture, this filter
      includes everyone who selected a given category, whether alone or in combination with another.
    </p>
  );

  if (!period) {
    return (
      <section className="section">
        <h2 className="section-heading">Entries, Actively Experiencing Homelessness &amp; Exits</h2>
        <p className="section-subhead">
          How many people are entering, staying active in, and leaving our homelessness response system? Pick a
          year, then click a quarter to zoom into it.
        </p>
        <FilterBar>
          <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
          <YearSelect years={years} value={year} onChange={onYearChange} />
          <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} />
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

  const periodLabel = quarter ? formatQuarterLabel(quarter) : String(year);
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
        then click a quarter to zoom into it: the cards and chart below always show the same period.
      </p>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={onPopulationChange} />
        <YearSelect years={years} value={year} onChange={onYearChange} />
        <DemographicTypeSelect value={demographicType} onChange={onDemographicTypeChange} />
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
          <button type="button" aria-label="Show an older quarter" disabled={!quarter || quarterIdx <= 0} onClick={() => stepQuarter(-1)}>
            ‹
          </button>
          <button
            type="button"
            aria-label="Show a more recent quarter"
            disabled={!quarter || quarterIdx >= allQuarters.length - 1}
            onClick={() => stepQuarter(1)}
          >
            ›
          </button>
        </div>
      </div>
      <QuarterPills quarters={quartersForYear} selected={quarter} onSelect={setSelectedQuarter} />
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
                goodDirection="down"
              />
              <KpiCard
                label="Return from Housed"
                value={period.inflow.return_from_housed.value?.toLocaleString()}
                marker={period.inflow.return_from_housed.marker}
                percent={percentOfExperienced(period.inflow.return_from_housed, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_housed, previousPeriod?.inflow?.return_from_housed)}
                goodDirection="down"
              />
              <KpiCard
                label="Return from Inactive"
                value={period.inflow.return_from_inactive.value?.toLocaleString()}
                marker={period.inflow.return_from_inactive.marker}
                percent={percentOfExperienced(period.inflow.return_from_inactive, totalExperienced)}
                trendDirection={trendDirectionFor(period.inflow.return_from_inactive, previousPeriod?.inflow?.return_from_inactive)}
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
                goodDirection={null}
              />
              <KpiCard
                label="Permanently Housed"
                value={period.outflow.permanently_housed.value?.toLocaleString()}
                marker={period.outflow.permanently_housed.marker}
                percent={percentOfExperienced(period.outflow.permanently_housed, totalExperienced)}
                trendDirection={trendDirectionFor(period.outflow.permanently_housed, previousPeriod?.outflow?.permanently_housed)}
                goodDirection="up"
              />
              <KpiCard
                label="Deceased"
                value={period.outflow.deceased.value?.toLocaleString()}
                marker={period.outflow.deceased.marker}
                percent={percentOfExperienced(period.outflow.deceased, totalExperienced)}
                trendDirection={trendDirectionFor(period.outflow.deceased, previousPeriod?.outflow?.deceased)}
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
                  goodDirection={null}
                />
              )}
            </div>
          </div>
          <FlowSankeyChart data={period} periodLabel={periodLabel} isFullYear={!quarter} populationSegment={populationSegment} />
        </>
      )}
    </section>
  );
}
