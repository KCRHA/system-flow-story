import { useMemo, useState } from "react";
import Scrolly from "../Scrolly.jsx";
import FilterBar, { YearSelect } from "../FilterBar.jsx";
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

export default function CapacitySection({ capacityRows, capacityQuarterlyRows, capacityYearlyRows }) {
  const years = useMemo(
    () => [...new Set(capacityRows.map((r) => Number(r.month.slice(0, 4))))].sort((a, b) => b - a),
    [capacityRows]
  );
  const [selectedYear, setSelectedYear] = useState(null);
  const year = selectedYear ?? years[0];

  const yearRows = useMemo(
    () => capacityRows.filter((r) => Number(r.month.slice(0, 4)) === year).sort((a, b) => a.month.localeCompare(b.month)),
    [capacityRows, year]
  );
  const monthsInYear = useMemo(() => [...new Set(yearRows.map((r) => r.month))].sort(), [yearRows]);
  const latestMonth = monthsInYear.at(-1);
  const isComplete = monthsInYear.length === 12;

  const unitsRows = useMemo(
    () => yearRows.filter((r) => r.month === latestMonth && UNITS_AND_UTILIZATION_TYPES.includes(r.project_type)),
    [yearRows, latestMonth]
  );

  // Utilization always shows a trailing 3-year (12-quarter) window
  // (independent of the Year selector above, which drives the other two
  // steps) — visually aligned with Resource Access's sparklines, which
  // show the same span. Sourced from the separate quarterly export
  // (dashboard_capacity_quarterly.json), not the monthly table — same
  // per-night-count basis either way, but the source's own native
  // 'Quarter' rows are used for consistency with the yearly Turnover data.
  const last12Quarters = useMemo(
    () => [...new Set(capacityQuarterlyRows.map((r) => r.quarter))].sort().slice(-12),
    [capacityQuarterlyRows]
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

  if (!yearRows.length) {
    return (
      <section className="section">
        <h2 className="section-heading">System Capacity</h2>
        <p className="section-subhead">
          How much shelter and housing capacity exists in our system, how full is it running, and how quickly do
          people move through it?
        </p>
        <FilterBar>
          <YearSelect years={years} value={year} onChange={setSelectedYear} />
        </FilterBar>
        <p className="suppressed-note">No data available for this year.</p>
      </section>
    );
  }

  const asOfLabel = isComplete ? `as of ${formatMonthLabel(latestMonth)}` : `as of ${formatMonthLabel(latestMonth)} (year to date)`;

  const steps = [
    `How many units exist in the system? Here's the total by project type, ${asOfLabel}. (Rapid Re-Housing is temporarily excluded here and in Utilization below — see Turnover for RRH figures.)`,
    `How full is that capacity, quarter by quarter over the last three years? Utilization near 100% means a project type has little room left.`,
    `Of everyone served by each project type this year, what share exited? What counts as "good" here depends on the program: permanent housing succeeds when people stay housed — a lower share exiting. Shelter and transitional programs succeed when people move through toward something more stable — a higher share exiting.`,
  ];

  return (
    <section className="section">
      <h2 className="section-heading">System Capacity</h2>
      <p className="section-subhead">
        How much shelter and housing capacity exists in our system, how full is it running, and how quickly do
        people move through it?
      </p>
      <FilterBar>
        <YearSelect years={years} value={year} onChange={setSelectedYear} />
      </FilterBar>
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
