import { useMemo } from "react";
import ChartLegend from "../ChartLegend.jsx";
import CapacityCardChart from "../charts/CapacityCardChart.jsx";

const PROJECT_TYPES = ["es", "th", "rrh", "ph"];
// Rapid Re-Housing has no fixed inventory (time-limited rental assistance in
// private-market housing — see the note under the card row below), so it's
// excluded from the unit-count/utilization cards, but still appears in
// turnover, which only needs enrollment/exit counts, not units.
const UNITS_AND_UTILIZATION_TYPES = PROJECT_TYPES.filter((t) => t !== "rrh");

const CARD_LABELS = { es: "Emergency shelter", th: "Transitional housing", ph: "Permanent housing" };
const TURNOVER_LABELS = { es: "Emergency shelter", th: "Transitional housing", rrh: "Rapid re-housing", ph: "Permanent housing" };
const GOAL_TEXT = {
  es: "Goal is for people to move on to stable housing",
  th: "Goal is for people to move on to stable housing",
  rrh: "Goal is for people to move on and keep their housing",
  ph: "Goal is for people to stay housed",
};

function monthAbbrev(month) {
  return new Date(month).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
}
function shortMonthYearLabel(month) {
  const d = new Date(month);
  return `${d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
}

export default function CapacitySection({ capacityRows, capacityYearlyRows, year, demographicType }) {
  const yearRows = useMemo(
    () => capacityRows.filter((r) => Number(r.month.slice(0, 4)) === year).sort((a, b) => a.month.localeCompare(b.month)),
    [capacityRows, year]
  );
  const monthsInYear = useMemo(() => [...new Set(yearRows.map((r) => r.month))].sort(), [yearRows]);
  const latestMonth = monthsInYear.at(-1);
  // Mirrors LengthSection's own isPartialYear: a year missing a December row
  // is necessarily the current, still-in-progress one — every completed year
  // in this export runs through December.
  const isPartialYear = monthsInYear.length > 0 && !monthsInYear.some((m) => m.slice(5, 7) === "12");
  const throughAbbrev = isPartialYear ? monthAbbrev(latestMonth) : null;

  // One snapshot per year (that year's last available month) from 2021
  // through the selected year, per project type — the trend each card's own
  // mini chart plots. Built from the full capacityRows history (not
  // yearRows, which is scoped to the selected year alone), so each card
  // shows multiple years of capacity/utilization even though only the
  // selected year's headline figures are called out in text.
  const cardYears = useMemo(() => {
    const years = [...new Set(capacityRows.map((r) => Number(r.month.slice(0, 4))))].filter((y) => y <= year);
    return years.sort((a, b) => a - b);
  }, [capacityRows, year]);
  const cardSeries = useMemo(
    () =>
      UNITS_AND_UTILIZATION_TYPES.map((type) => ({
        project_type: type,
        points: cardYears.map((y) => {
          const monthsForYear = capacityRows
            .filter((r) => r.project_type === type && Number(r.month.slice(0, 4)) === y)
            .sort((a, b) => a.month.localeCompare(b.month));
          const last = monthsForYear.at(-1);
          return {
            year: y,
            month: last?.month ?? null,
            units_in_system: last?.units_in_system ?? null,
            pct_utilization: last?.pct_utilization ?? null,
          };
        }),
      })),
    [capacityRows, cardYears]
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
          How much capacity does our system have, and how quickly does it turn over?
          {demographicNote}
        </h2>
        <p className="suppressed-note">No data available for this year.</p>
      </section>
    );
  }

  return (
    <section className="section">
      <h2 className="section-heading">
        How much capacity does our system have, and how quickly does it turn over?
        {demographicNote}
      </h2>

      <div className="section-header">
        <div>
          <h3 className="chart-frame-title">How full is each program type?</h3>
          <p className="section-subhead">
            Utilization near 100% means a program type has little room left. Across years and program types,
            utilization stays consistently high, so the system is running near capacity.
          </p>
        </div>
        <ChartLegend
          items={[
            { kind: "line", color: "var(--text-navy)", label: "Capacity" },
            { kind: "band", color: "var(--chart-7)", label: "In use" },
            { kind: "ring", color: "var(--text-navy)", label: "Selected year" },
          ]}
        />
      </div>
      <div className="capacity-card-row">
        {UNITS_AND_UTILIZATION_TYPES.map((type) => {
          const series = cardSeries.find((s) => s.project_type === type);
          const latest = series?.points.at(-1);
          const pct = latest?.pct_utilization != null ? Math.round(latest.pct_utilization * 100) : null;
          return (
            <div className="kpi-card capacity-card" key={type}>
              <h4 className="length-panel-title">{CARD_LABELS[type]}</h4>
              {latest?.units_in_system != null ? (
                <>
                  <div className="kpi-value-row">
                    <span className="kpi-value">{Math.round(latest.units_in_system).toLocaleString()}</span>
                    <span className="kpi-percent-total">units as of {shortMonthYearLabel(latest.month)}</span>
                  </div>
                  <p className="kpi-description">
                    {pct != null ? `${pct}%` : "—"} in use in {year}
                    {isPartialYear && ` (through ${throughAbbrev})`}
                  </p>
                </>
              ) : (
                <p className="suppressed-note">No data available.</p>
              )}
              <div className="capacity-card-chart">
                <CapacityCardChart points={series?.points ?? []} />
              </div>
            </div>
          );
        })}
      </div>
      <p className="chart-note-left">
        Rapid re-housing isn't included. It provides time-limited rental assistance in private-market housing, so
        there are no fixed units in our inventory to measure.
      </p>

      <div className="section-header">
        <h3 className="chart-frame-title">How quickly does each program type turn over?</h3>
        <ChartLegend
          items={[
            { kind: "square", color: "var(--chart-2)", label: "Exited" },
            { kind: "square", color: "var(--gray-light)", label: "Still in program" },
          ]}
        />
      </div>
      <div className="turnover-card">
        {turnoverRows.map((row) => {
          const pctExited = row.pct_exited != null ? Math.round(row.pct_exited * 100) : null;
          return (
            <div className="turnover-row" key={row.project_type}>
              <div className="turnover-col">
                <h4 className="length-panel-title">{TURNOVER_LABELS[row.project_type]}</h4>
                <p className="kpi-description">{GOAL_TEXT[row.project_type]}</p>
              </div>
              <div className="turnover-col">
                {row.households_per_unit != null ? (
                  <>
                    <div className="kpi-value-row">
                      <span className="kpi-value">{row.households_per_unit.toFixed(1)}</span>
                    </div>
                    <p className="kpi-description">
                      average households served per unit in {year}
                      {isPartialYear && ` (through ${throughAbbrev})`}
                    </p>
                  </>
                ) : (
                  <>
                    <p className="turnover-no-data">No per-unit figure</p>
                    <p className="kpi-description">See note below</p>
                  </>
                )}
              </div>
              <div className="turnover-col">
                <p className="turnover-bar-label">
                  {pctExited != null ? `${pctExited}%` : "No data"} of people served in {year} exited
                </p>
                <div className="turnover-bar-track">
                  {pctExited != null && <div className="turnover-bar-fill" style={{ width: `${pctExited}%` }} />}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <p className="chart-note-left">
        Rapid re-housing has no per-unit figure. It provides time-limited rental assistance in private-market
        housing, so there are no fixed units in our inventory to measure.
      </p>

      <h3 className="kpi-group-heading">What this shows</h3>
      <p className="chart-analysis">
        Capacity shows how much room the system has, and turnover shows how many people each unit serves in a year.{" "}
        <strong>Permanent housing succeeds when people stay housed.</strong>{" "}
        <strong>Shelter, Transitional, and Rapid-Rehousing succeed when people move on to stable housing</strong>, so
        where people go matters as much as how many people leave. For length of stay, see the{" "}
        <a href="https://kcrha.org/community-data/system-performance/" target="_blank" rel="noreferrer">
          System Performance Dashboard
        </a>
        .
      </p>
    </section>
  );
}
