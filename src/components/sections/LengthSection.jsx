import { useMemo } from "react";
import KpiCard from "../KpiCard.jsx";
import ChartLegend from "../ChartLegend.jsx";
import LengthByExitGrid from "../charts/LengthByExitGrid.jsx";
import ReturnCohortChart from "../charts/ReturnCohortChart.jsx";
import { filterRows, distinctValues } from "../../lib/loadData.js";
import { subjectFor } from "../../lib/demographics.js";
import { trendDirectionFor, trendPillText, trendPillTextPoints } from "../../lib/trend.js";
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

  // The return-rate headline card is a standalone "most recent quarter"
  // snapshot, not tied to the Year/quarter/month drill-down the way the
  // length headline above is — it says so explicitly ("the most recent
  // quarter with six months of follow-up"), so it's built from every
  // window_complete cohort rather than scopedReturns' Year-capped, 8-quarter
  // window. Compared against the quarter right before it — headlineReturnRows
  // is already sorted ascending and window_complete-only, so the second-to-
  // last row is exactly that.
  const headlineReturnRows = useMemo(
    () =>
      filterRows(returnCohortRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => r.window_complete)
        .sort((a, b) => a.exit_quarter.localeCompare(b.exit_quarter)),
    [returnCohortRows, populationSegment, filterDimension, filterCategory]
  );
  const latestReturnCohort = headlineReturnRows.at(-1);
  const previousReturnCohort = headlineReturnRows.at(-2);
  // pct_returned is always null exactly when suppression_marker or
  // return_suppression_marker is set (see pipeline/suppression.py) — one
  // marker covers both cases for the headline cell.
  const returnRateCell = (row) =>
    row && {
      value: row.pct_returned != null ? row.pct_returned * 100 : null,
      marker: row.suppression_marker || row.return_suppression_marker,
    };
  const returnRateCurrent = returnRateCell(latestReturnCohort);
  const returnRatePrevious = returnRateCell(previousReturnCohort);
  const returnRatePreviousLabel = previousReturnCohort ? formatQuarterLabel(previousReturnCohort.exit_quarter) : null;
  const latestReturnQuarterLabel = latestReturnCohort ? formatQuarterLabel(latestReturnCohort.exit_quarter) : null;

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
      <h3 className="kpi-group-heading">What this shows</h3>
      <p className="chart-analysis">
        The time people are active in our system varies widely. Some people exit quickly, while others stay engaged
        for a long time as they wait for housing resources. A longer time isn't always a bad sign, since connecting
        people to housing takes time and staying engaged is better than losing contact. The goal is for people to
        stay connected until they're housed, and for that time to be as short as possible.
      </p>
      <hr className="definitions-divider" />
      <h2 className="section-heading">Do people who exit our system to permanent housing stay housed?</h2>
      <p className="section-subhead">Follows people for six months after they exit our system to permanent housing.</p>
      {latestReturnCohort ? (
        <div className="kpi-row kpi-row-hero">
          <KpiCard
            layout="stat"
            value={returnRateCurrent.marker ? undefined : returnRateCurrent.value != null ? `${Math.round(returnRateCurrent.value)}%` : undefined}
            marker={returnRateCurrent.marker}
            description={`returned to homelessness within six months, among ${subject} who exited our system to permanent housing in ${latestReturnQuarterLabel} (the most recent quarter with six months of follow-up)`}
            trendDirection={trendDirectionFor(returnRateCurrent, returnRatePrevious)}
            trendText={trendPillTextPoints(returnRateCurrent, returnRatePrevious, returnRatePreviousLabel)}
            goodDirection="down"
          />
        </div>
      ) : (
        <p className="chart-note">No data for this selection.</p>
      )}
      <div className="chart-frame-box">
        <p className="chart-frame-title">People who exited our system to permanent housing, by quarter of exit</p>
        <ChartLegend
          items={[
            { kind: "square", color: "var(--chart-2)", label: "Stayed housed" },
            { kind: "square", color: "var(--chart-3)", label: "Returned within six months" },
          ]}
        />
        <ReturnCohortChart rows={scopedReturns} />
        <p className="chart-group-caption">Recent quarters appear once six months have passed.</p>
      </div>
      <h3 className="kpi-group-heading">What this shows</h3>
      <p className="chart-analysis">
        A return means someone who exited our system to permanent housing became active in our system again within
        six months. Fewer returns suggest housing placements are lasting.
      </p>
    </section>
  );
}
