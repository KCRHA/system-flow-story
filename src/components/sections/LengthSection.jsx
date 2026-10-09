import { useMemo } from "react";
import KpiCard from "../KpiCard.jsx";
import LengthByExitGrid from "../charts/LengthByExitGrid.jsx";
import ReturnCohortChart from "../charts/ReturnCohortChart.jsx";
import { filterRows, distinctValues } from "../../lib/loadData.js";
import { subjectFor } from "../../lib/demographics.js";
import { trendDirectionFor, trendPillText } from "../../lib/trend.js";
import { formatMonthLabel, formatQuarterLabel } from "../../lib/periodLabels.js";

export default function LengthSection({
  lengthRows,
  lengthByExitRows,
  lengthHeadlineRows,
  lengthHeadlineMonthlyRows,
  lengthHeadlineQuarterlyRows,
  returnCohortRows,
  populationSegment,
  demographicType,
  demographicCategory,
  filterDimension,
  filterCategory,
  year,
  periodEndMonth,
  selectedQuarter,
  selectedMonth,
}) {
  // Last 2 years, ending at periodEndMonth when OutflowSection's own
  // quarter/month drill-down is active (e.g. picking June 2024 up there
  // ends this window at June 2024, spanning back to July 2022 — see
  // OutflowSection's own periodEndMonth comment for exactly what resolves
  // to what), otherwise at the selected Year's end (e.g. picking 2024 ends
  // the window at Dec 2024, not the latest month overall) — same Year
  // selector OutflowSection/CapacitySection use, so switching years moves
  // every time-series chart on the page together even with no quarter/
  // month drilled into. Full history is available but a shorter trailing
  // window keeps this legible. scopedLength feeds the "Still Active" panel
  // directly (it's already exactly that distribution — see build_length.py);
  // scopedByExit feeds the other panels, filtered by exit_type inside
  // LengthByExitGrid.
  const effectiveEndMonth = periodEndMonth ?? `${year}-12-31`;
  const scopedLength = useMemo(
    () =>
      filterRows(lengthRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => r.month <= effectiveEndMonth)
        .sort((a, b) => a.month.localeCompare(b.month))
        .slice(-24),
    [lengthRows, populationSegment, filterDimension, filterCategory, effectiveEndMonth]
  );
  const scopedByExit = useMemo(
    () =>
      filterRows(lengthByExitRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => r.month <= effectiveEndMonth)
        .sort((a, b) => a.month.localeCompare(b.month))
        .slice(-24 * 3), // 3 exit_types share this window — slice generously, each panel re-filters its own slice
    [lengthByExitRows, populationSegment, filterDimension, filterCategory, effectiveEndMonth]
  );
  // Only cohorts whose 6-month return window has fully elapsed have a
  // reportable rate at all (see window_complete in dashboard_return_cohorts.json)
  // — everything more recent is excluded rather than shown as a partial/
  // misleading rate. The most recent 8 of those complete quarters (ending
  // at the selected Year, same as scopedLength above) is what actually
  // renders, i.e. roughly the last 2 years.
  const scopedReturns = useMemo(
    () =>
      filterRows(returnCohortRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => r.window_complete && Number(r.exit_quarter.slice(0, 4)) <= year)
        .sort((a, b) => a.exit_quarter.localeCompare(b.exit_quarter))
        .slice(-8),
    [returnCohortRows, populationSegment, filterDimension, filterCategory, year]
  );

  // The headline KPI card's universe matches whatever month/quarter/year
  // OutflowSection's own pills have drilled into (selectedMonth ??
  // selectedQuarter ?? year — same priority buildFlowPeriod/OutflowSection's
  // own `period` use), not always the full Year — each grain has its own
  // pooled table (build_length_by_exit.py's build_length_headline_monthly_
  // /_quarterly_/_rows), since "everyone active at any point in the period,
  // measured as of their exit date or period-end if still active" can't be
  // reconstructed by summing/averaging a finer or coarser grain's own rows
  // client-side (same reasoning as dashboard_flow_monthly/quarterly/yearly).
  const scopedHeadlineMonthly = useMemo(
    () => filterRows(lengthHeadlineMonthlyRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [lengthHeadlineMonthlyRows, populationSegment, filterDimension, filterCategory]
  );
  const scopedHeadlineQuarterly = useMemo(
    () => filterRows(lengthHeadlineQuarterlyRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [lengthHeadlineQuarterlyRows, populationSegment, filterDimension, filterCategory]
  );
  const scopedHeadlineYearly = useMemo(
    () => filterRows(lengthHeadlineRows, { populationSegment, dimension: filterDimension, category: filterCategory }),
    [lengthHeadlineRows, populationSegment, filterDimension, filterCategory]
  );
  const allHeadlineMonths = useMemo(() => distinctValues(scopedHeadlineMonthly, "month").sort(), [scopedHeadlineMonthly]);
  const allHeadlineQuarters = useMemo(() => distinctValues(scopedHeadlineQuarterly, "quarter").sort(), [scopedHeadlineQuarterly]);

  const headlineGrain = selectedMonth ? "month" : selectedQuarter ? "quarter" : "year";
  const headlinePeriodCol = headlineGrain === "month" ? "month" : headlineGrain === "quarter" ? "quarter" : "year";
  const headlinePeriodKey = selectedMonth ?? selectedQuarter ?? year;
  const headlineRows =
    headlineGrain === "month" ? scopedHeadlineMonthly : headlineGrain === "quarter" ? scopedHeadlineQuarterly : scopedHeadlineYearly;
  // Index into whichever grain's own sorted period list resolves "the
  // period immediately before this one" — same prior-period fallback
  // OutflowSection's own previousPeriod uses for its KPI cards' trend arrow,
  // just derived from the length-headline tables instead of the flow ones
  // so this section stays self-contained.
  const previousHeadlinePeriodKey =
    headlineGrain === "month"
      ? allHeadlineMonths[allHeadlineMonths.indexOf(selectedMonth) - 1] ?? null
      : headlineGrain === "quarter"
        ? allHeadlineQuarters[allHeadlineQuarters.indexOf(selectedQuarter) - 1] ?? null
        : year - 1;

  const headlineRow = headlineRows.find((r) => r[headlinePeriodCol] === headlinePeriodKey);
  const previousHeadlineRow =
    previousHeadlinePeriodKey != null ? headlineRows.find((r) => r[headlinePeriodCol] === previousHeadlinePeriodKey) : undefined;
  const headlineCell = headlineRow && { value: headlineRow.median_days, marker: headlineRow.suppression_marker };
  const previousHeadlineCell = previousHeadlineRow && {
    value: previousHeadlineRow.median_days,
    marker: previousHeadlineRow.suppression_marker,
  };
  const headlinePeriodLabel =
    headlineGrain === "month" ? formatMonthLabel(selectedMonth) : headlineGrain === "quarter" ? formatQuarterLabel(selectedQuarter) : String(year);
  const previousHeadlinePeriodLabel = !previousHeadlineRow
    ? null
    : headlineGrain === "month"
      ? formatMonthLabel(previousHeadlinePeriodKey)
      : headlineGrain === "quarter"
        ? formatQuarterLabel(previousHeadlinePeriodKey)
        : String(previousHeadlinePeriodKey);

  // The headline tooltip below says "still-active people are counted as of
  // {year}'s year-end" — true for a complete year, but wrong for the
  // current, still-in-progress one (build_length_headline_rows actually
  // counts them as of the year's *last available month*, which isn't
  // December yet). Detected the same way OutflowSection's own "Full Year
  // (through Aug)" pill label does (quartersForYear.length < 4), just from
  // dashboard_length_monthly's "overall" rows instead of quarterly flow
  // data, since that's what's already in scope here — every population
  // segment's "overall" dimension has one row per month it has any data
  // for at all, so a year missing a December row is necessarily the
  // current, incomplete one. Only relevant in the full-year view — a
  // selected month is always one real, complete month, and a selected
  // quarter is only ever published once all 3 of its months are (see
  // build_length_headline_quarterly_rows' own completeness guard), so
  // neither needs this caveat.
  const monthsThisYear = useMemo(
    () =>
      filterRows(lengthRows, { populationSegment, dimension: "overall", category: "Overall" })
        .filter((r) => Number(r.month.slice(0, 4)) === year)
        .map((r) => r.month)
        .sort(),
    [lengthRows, populationSegment, year]
  );
  const isPartialYear =
    headlineGrain === "year" && monthsThisYear.length > 0 && !monthsThisYear.some((m) => m.slice(5, 7) === "12");
  const throughLabel = isPartialYear
    ? new Date(monthsThisYear.at(-1)).toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    : null;

  // Scoping to a demographic category isn't visible once a reader has
  // scrolled past the filter controls above (OutflowSection), so the
  // blurb text says who's being measured explicitly — see subjectFor above.
  const subject = subjectFor(populationSegment, demographicType, demographicCategory);

  return (
    <section className="section">
      <h2 className="section-heading">How long are {subject} actively experiencing homelessness in our system?</h2>
      <p className="section-subhead">Time from becoming active in our system until people exit.</p>
      <div className="kpi-row kpi-row-hero">
        <KpiCard
          label="Median days experiencing homelessness"
          value={headlineCell?.value != null ? `${Math.round(headlineCell.value).toLocaleString()} days` : undefined}
          marker={headlineCell?.marker}
          trendDirection={trendDirectionFor(headlineCell, previousHeadlineCell)}
          trendText={trendPillText(headlineCell, previousHeadlineCell, previousHeadlinePeriodLabel)}
          goodDirection="down"
          info={{
            title: "Median days experiencing homelessness",
            body:
              headlineGrain === "month"
                ? `All ${subject}, active at any point in ${headlinePeriodLabel}, counted as of their exit date if they left the system (Permanently Housed, Inactive, Deceased, or Aged Out) or as of ${headlinePeriodLabel}'s month-end if they're still active.`
                : headlineGrain === "quarter"
                  ? `All ${subject}, active at any point in ${headlinePeriodLabel}, counted as of their exit date if they left the system (Permanently Housed, Inactive, Deceased, or Aged Out) or as of ${headlinePeriodLabel}'s quarter-end if they're still active.`
                  : isPartialYear
                    ? `All ${subject}, active at any point in ${year} so far (through ${throughLabel}), counted as of their exit date if they left the system (Permanently Housed, Inactive, Deceased, or Aged Out) or as of the most recent available month if they're still active.`
                    : `All ${subject}, active at any point in ${year}, counted as of their exit date if they left the system (Permanently Housed, Inactive, Deceased, or Aged Out) or as of ${year}'s year-end if they're still active.`,
          }}
        />
      </div>
      <div className="chart-frame-box">
        <p className="chart-frame-title">Days experiencing homelessness, by last housing status</p>
        <LengthByExitGrid byExitRows={scopedByExit} stillActiveRows={scopedLength} populationSegment={populationSegment} />
      </div>
      <h3 className="kpi-group-heading">Returning to homelessness after exiting</h3>
      <p className="chart-analysis">
        A related question: of {subject} who exit to permanent housing, how many return to homelessness within six
        months? Shown are the last two years of exit cohorts old enough that we can measure this accurately. More
        recent exits haven't had six months to potentially return yet.
      </p>
      <div className="chart-frame-box">
        <p className="chart-frame-label">Returned to Homelessness within 6 Months</p>
        <ReturnCohortChart rows={scopedReturns} />
      </div>
    </section>
  );
}
