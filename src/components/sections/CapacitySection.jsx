import { useMemo } from "react";
import Scrolly from "../Scrolly.jsx";
import CapacityUnitsChart from "../charts/CapacityUnitsChart.jsx";
import CapacityUtilizationChart from "../charts/CapacityUtilizationChart.jsx";
import CapacityTurnoverChart from "../charts/CapacityTurnoverChart.jsx";

const PROJECT_TYPES = ["ph", "th", "es", "rrh"];
// Rapid Re-Housing is temporarily excluded from the unit-count and
// utilization charts (not turnover/throughput, which still needs it) —
// see CapacitySection request to drop it "for now".
const UNITS_AND_UTILIZATION_TYPES = PROJECT_TYPES.filter((t) => t !== "rrh");

function formatMonthLabel(month) {
  const [year, m] = month.split("-");
  const date = new Date(Number(year), Number(m) - 1, 1);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export default function CapacitySection({ capacityRows, capacityQuarterlyRows, capacityYearlyRows, year, demographicType }) {
  const yearRows = useMemo(
    () => capacityRows.filter((r) => Number(r.month.slice(0, 4)) === year).sort((a, b) => a.month.localeCompare(b.month)),
    [capacityRows, year]
  );
  const monthsInYear = useMemo(() => [...new Set(yearRows.map((r) => r.month))].sort(), [yearRows]);
  const latestMonth = monthsInYear.at(-1);

  const unitsRows = useMemo(
    () => yearRows.filter((r) => r.month === latestMonth && UNITS_AND_UTILIZATION_TYPES.includes(r.project_type)),
    [yearRows, latestMonth]
  );

  // Utilization always shows a trailing 3-year (12-quarter) window ending
  // at the selected Year (e.g. picking 2024 shows a window ending Q4
  // 2024, not the latest quarter overall) — same Year selector the other
  // two steps use, so switching years moves every chart in this section
  // together. Sourced from the separate quarterly export
  // (dashboard_capacity_quarterly.json), not the monthly table — same
  // per-night-count basis either way, but the source's own native
  // 'Quarter' rows are used for consistency with the yearly Turnover data.
  const last12Quarters = useMemo(
    () =>
      [...new Set(capacityQuarterlyRows.map((r) => r.quarter))]
        .filter((quarter) => Number(quarter.slice(0, 4)) <= year)
        .sort()
        .slice(-12),
    [capacityQuarterlyRows, year]
  );
  const utilizationSeries = useMemo(
    () =>
      UNITS_AND_UTILIZATION_TYPES.map((type) => ({
        project_type: type,
        points: last12Quarters.map((quarter) => {
          const row = capacityQuarterlyRows.find((r) => r.project_type === type && r.quarter === quarter);
          return { quarter, pct_utilization: row?.pct_utilization ?? null };
        }),
      })),
    [capacityQuarterlyRows, last12Quarters]
  );

  // Sourced from the separate yearly export (dashboard_capacity_yearly.json),
  // not derived from yearRows/the monthly table — EnrolledDuringTimeframe
  // is a monthly snapshot, so summing 12 months would count a household
  // once per month of their stay instead of once for the year.
  const turnoverRows = useMemo(
    () =>
      PROJECT_TYPES.map((type) => {
        const row = capacityYearlyRows.find((r) => r.project_type === type && r.year === year);
        return {
          project_type: type,
          pct_exited: row?.pct_exited ?? null,
          households_per_unit: row?.households_per_unit ?? null,
          exited: row?.exited ?? null,
          active: row?.active ?? null,
        };
      }),
    [capacityYearlyRows, year]
  );

  // Capacity is aggregate inventory/utilization data (see build_capacity.py) —
  // it has no per-person dimension/category breakdown at all, unlike
  // Outflow/Length, so a demographic filter selected up top silently has no
  // effect here. Flagged only when a filter is actually active, so the note
  // doesn't clutter the default "All" view.
  const demographicNote = demographicType !== "overall" && (
    <span className="section-heading-note"> (demographic filters do not apply)</span>
  );

  if (!yearRows.length) {
    return (
      <section className="section">
        <h2 className="section-heading">
          System Capacity
          {demographicNote}
        </h2>
        <p className="section-subhead">
          How much shelter and housing capacity exists in our system, how full is it running, and how quickly do
          people move through it?
        </p>
        <p className="suppressed-note">No data available for this year.</p>
      </section>
    );
  }

  const steps = [
    // A point-in-time snapshot (unitsRows is one specific month's rows,
    // not an accumulation across the year), so the label is just "as of
    // {month}" — no "(year to date)" qualifier, which would incorrectly
    // imply a running total building up since January.
    `How many units exist in the system? Here's the total by project type, as of ${formatMonthLabel(latestMonth)}.`,
    `How full is that capacity, quarter by quarter over the last three years in the reporting period? Utilization near 100% means a project type has little room left.`,
    `Of everyone served by each project type in ${year}, what share exited? What counts as "good" here depends on the program: permanent housing succeeds when people stay housed (a lower share exiting). Shelter and transitional programs succeed when people move through toward something more stable (a higher share exiting).`,
  ];

  return (
    <section className="section">
      <h2 className="section-heading">
        System Capacity
        {demographicNote}
      </h2>
      <p className="section-subhead">
        How much shelter and housing capacity exists in our system, how full is it running, and how quickly do
        people move through it?
      </p>
      <Scrolly
        steps={steps}
        renderGraphic={() => (
          <div className="scrolly-graphic-stack">
            <CapacityUnitsChart rows={unitsRows} />
            <CapacityUtilizationChart series={utilizationSeries} />
            <CapacityTurnoverChart rows={turnoverRows} />
          </div>
        )}
      />
    </section>
  );
}
