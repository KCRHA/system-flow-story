// Print-only view for the YYA collaborative data walk: one 11x17 portrait
// page per (station, population, selection), year to date. Reuses the
// dashboard's own chart components so the printouts match what people see
// online. Open /print.html?station=overview|inflow|outflow|length (or no
// param for all four stations) and print to PDF.
import { useEffect, useMemo, useState } from "react";
import KpiCard from "../components/KpiCard.jsx";
import ChartLegend from "../components/ChartLegend.jsx";
import FlowSankeyChart from "../components/charts/FlowSankeyChart.jsx";
import HomelessnessTrendChart from "../components/charts/HomelessnessTrendChart.jsx";
import LengthChart from "../components/charts/LengthChart.jsx";
import ReturnCohortChart from "../components/charts/ReturnCohortChart.jsx";
import { MEASURES } from "../components/FilterBar.jsx";
import { filterRows, distinctValues, resolveCell } from "../lib/loadData.js";
import { buildFlowPeriod, sumCellsForQuarter } from "../lib/sankeyData.js";
import { formatMonthLabel, formatQuarterLabel } from "../lib/periodLabels.js";

const BASE = import.meta.env.BASE_URL;
const YEAR = 2026;

const SELECTIONS = [
  { label: "All", dimension: "overall", category: "Overall" },
  { label: "Black or African American", dimension: "race_black", category: "Included" },
  { label: "Indigenous", dimension: "race_aian", category: "Included" },
  { label: "Unsheltered", dimension: "unsheltered_in_period", category: "Included" },
  { label: "Households with Adults and Children", dimension: "household_type_adults_children", category: "Included" },
  { label: "Engaged with Coordinated Entry", dimension: "project_engaged_ce", category: "Included" },
];

const POPULATIONS = [
  { key: "yya", label: "YYA" },
  { key: "all_population", label: "All Population" },
];

const STATIONS = {
  overview: "Overview",
  inflow: "Inflow",
  outflow: "Outflow",
  length: "Length of Time",
};

const measure = (value) => MEASURES.find((m) => m.value === value);
const INFLOW_MEASURES = ["total_entered_the_system", "indiv_newly_homeless", "indiv_return_from_housed", "indiv_return_from_inactive"].map(measure);
const OUTFLOW_MEASURES = ["total_exited_the_system", "indiv_inactive", "indiv_permanently_housed", "indiv_aged_out"].map(measure);

const LENGTH_PANELS = [
  { key: "permanently_housed", label: "Permanently Housed" },
  { key: "inactive", label: "Inactive (excluding deceased)" },
  { key: "still_active", label: "Still Active" },
  { key: "aged_out", label: "Aged Out" },
];

async function fetchJson(path) {
  const res = await fetch(`${BASE}data/${path}`);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

function percentOf(cell, total) {
  if (!cell || cell.marker || !total) return null;
  return `${Math.round((cell.value / total) * 100)}%`;
}
function sumValues(cells) {
  if (cells.some((c) => !c || c.marker)) return null;
  return cells.reduce((s, c) => s + c.value, 0);
}

// Same trailing 12-quarter window OutflowSection's run chart uses for a
// full-year view of the selected year.
function trendPoints(quarterlyRows, m) {
  const quarters = distinctValues(quarterlyRows, "quarter")
    .filter((q) => q <= `${YEAR}-12-31`)
    .sort()
    .slice(-12);
  return quarters.map((q) => ({
    quarter: q,
    note: null,
    ...(m.components
      ? sumCellsForQuarter(quarterlyRows, q, m.components)
      : resolveCell(quarterlyRows.find((r) => r.quarter === q && r.flow_type === m.value), "count")),
  }));
}

function TrendCard({ rows, m, width, height }) {
  const points = useMemo(() => trendPoints(rows, m), [rows, m]);
  return (
    <div className="print-chart-card print-trend">
      <p className="print-chart-title">{m.label}</p>
      <HomelessnessTrendChart
        points={points}
        measureLabel={m.label}
        unitLabel={m.unitLabel}
        axisLabel={m.axisLabel}
        subject="people"
        selectedQuarter={null}
        width={width}
        height={height}
      />
    </div>
  );
}

function YyaOnlySlot({ label }) {
  return (
    <div className="print-chart-card print-yya-only">
      <p className="print-chart-title">{label}</p>
      <p>Aged Out applies only to youth and young adults, so this chart appears on YYA pages only.</p>
    </div>
  );
}

function PageHeader({ station, population, selection, through }) {
  return (
    <header className="print-header">
      <h1>
        {population.label} - {selection.label}
      </h1>
      <p>
        {STATIONS[station]} &middot; Year to date, January to {through.monthName} {YEAR}
      </p>
    </header>
  );
}

function PageFooter({ station, through }) {
  return (
    <footer className="print-footer">
      {station !== "length" && (
        <p>
          Run charts show the 12 most recent complete quarters, through {through.lastQuarterLabel}.
        </p>
      )}
      <p>
        * and ** mark numbers withheld to protect privacy, not zeros. * means fewer than 11 people. ** means 11 or
        more, hidden so a nearby small number can't be calculated.
      </p>
    </footer>
  );
}

function OverviewBody({ population, period, quarterly }) {
  const isYya = population.key === "yya";
  const entries = sumValues([period.inflow.newly_homeless, period.inflow.return_from_housed, period.inflow.return_from_inactive]);
  const exits = sumValues([period.outflow.inactive, period.outflow.permanently_housed, period.outflow.aged_out]);
  const card = (label, cell, total, percentLabel) => (
    <KpiCard
      label={label}
      value={cell.value?.toLocaleString()}
      marker={cell.marker}
      percent={percentOf(cell, total)}
      percentLabel={percentLabel}
    />
  );
  return (
    <>
      <div className="print-tiles">
        <div className="kpi-row kpi-row-hero">
          <KpiCard
            label={`Active in our system at any point in ${YEAR} so far`}
            value={period.experiencedHomelessness.value?.toLocaleString()}
            marker={period.experiencedHomelessness.marker}
          />
        </div>
        <h3 className="kpi-group-heading">Entered the system</h3>
        <div className="kpi-row print-row-3">
          {card("Newly experiencing homelessness", period.inflow.newly_homeless, entries, "of total entries")}
          {card("Returned from housed", period.inflow.return_from_housed, entries, "of total entries")}
          {card("Returned from inactive", period.inflow.return_from_inactive, entries, "of total entries")}
        </div>
        <h3 className="kpi-group-heading">Exited the system</h3>
        <div className="kpi-row print-row-3">
          {card("Inactive", period.outflow.inactive, exits, "of total exits")}
          {card("Permanently housed", period.outflow.permanently_housed, exits, "of total exits")}
          {isYya ? card("Aged Out", period.outflow.aged_out, exits, "of total exits") : <div className="print-tile-spacer" />}
        </div>
      </div>
      <div className="print-chart-card">
        <p className="print-chart-title">Status at the start and end of {YEAR} so far</p>
        <FlowSankeyChart data={period} periodLabel={`${YEAR} so far`} isFullYear populationSegment={population.key} width={900} height={485} />
      </div>
      <TrendCard rows={quarterly} m={measure("experienced_homelessness")} width={760} height={210} />
    </>
  );
}

function InflowBody({ population, period, quarterly }) {
  return (
    <>
      <div className="print-chart-card">
        <p className="print-chart-title">Status at the start and end of {YEAR} so far</p>
        <FlowSankeyChart data={period} periodLabel={`${YEAR} so far`} isFullYear populationSegment={population.key} width={900} height={480} />
      </div>
      <div className="print-grid-2">
        {INFLOW_MEASURES.map((m) => (
          <TrendCard key={m.value} rows={quarterly} m={m} width={420} height={245} />
        ))}
      </div>
    </>
  );
}

function OutflowBody({ population, quarterly, returns }) {
  const isYya = population.key === "yya";
  return (
    <>
      <div className="print-grid-2">
        {OUTFLOW_MEASURES.map((m) =>
          m.yyaOnly && !isYya ? (
            <YyaOnlySlot key={m.value} label={m.label} />
          ) : (
            <TrendCard key={m.value} rows={quarterly} m={m} width={420} height={270} />
          )
        )}
      </div>
      <div className="print-chart-card">
        <p className="print-chart-title">People who exited our system to permanent housing, by quarter of exit</p>
        <ChartLegend
          items={[
            { kind: "square", color: "var(--chart-2)", label: "Stayed housed" },
            { kind: "square", color: "var(--chart-3)", label: "Returned within six months" },
          ]}
        />
        {returns.length ? <ReturnCohortChart rows={returns} width={760} height={330} /> : <p className="chart-note">No data for this selection.</p>}
        <p className="chart-group-caption">Recent quarters appear once six months have passed.</p>
      </div>
    </>
  );
}

function LengthBody({ population, headline, panelRows, yMax }) {
  const isYya = population.key === "yya";
  return (
    <>
      <div className="kpi-row kpi-row-hero print-length-tile">
        <KpiCard
          label={`Median days experiencing homelessness, ${YEAR} so far`}
          value={headline?.median_days != null ? `${Math.round(headline.median_days).toLocaleString()} days` : undefined}
          marker={headline?.suppression_marker}
        />
      </div>
      <div className="print-chart-card">
        <p className="print-chart-title">Days experiencing homelessness, by last housing status</p>
        <ChartLegend
          items={[
            { kind: "line", color: "var(--chart-2)", label: "Median" },
            { kind: "band", color: "var(--chart-7)", label: "Middle 50% of people" },
          ]}
        />
        <div className="print-grid-2 print-grid-flat">
          {LENGTH_PANELS.map(({ key, label }, i) => {
            if (key === "aged_out" && !isYya) return <YyaOnlySlot key={key} label={label} />;
            const rows = panelRows[key];
            return (
              <div className="length-exit-panel" key={key}>
                <p className="length-panel-title">{label}</p>
                {rows.length ? (
                  <LengthChart
                    rows={rows}
                    width={420}
                    height={420}
                    compact
                    yMax={yMax}
                    yAxisLabel={i % 2 === 0 ? "Days active before exiting" : null}
                    isExit={key !== "still_active"}
                  />
                ) : (
                  <p className="chart-note">No data for this selection.</p>
                )}
              </div>
            );
          })}
        </div>
        <p className="chart-group-caption">
          One point per month, for whoever exited to that status (or remained active) that month, over the last 24
          months. The YYA and All Population pages for the same group use the same scale. Months with three or fewer
          people show the median only.
        </p>
      </div>
    </>
  );
}

export default function PrintApp() {
  const station = new URLSearchParams(window.location.search).get("station");
  const stations = station && STATIONS[station] ? [station] : Object.keys(STATIONS);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const dims = [...new Set(SELECTIONS.map((s) => s.dimension))];
    Promise.all([
      fetchJson("dashboard_flow_yearly.json"),
      fetchJson("dashboard_length_monthly.json"),
      fetchJson("dashboard_length_by_exit_monthly.json"),
      fetchJson("dashboard_length_headline_yearly.json"),
      fetchJson("dashboard_return_cohorts.json"),
      Promise.all(dims.map((d) => fetchJson(`dashboard_flow_quarterly_${d}.json`).then((rows) => [d, rows]))),
    ])
      .then(([flowYearly, length, lengthByExit, lengthHeadline, returnCohorts, quarterlyPairs]) =>
        setData({ flowYearly, length, lengthByExit, lengthHeadline, returnCohorts, quarterly: Object.fromEntries(quarterlyPairs) })
      )
      .catch(setError);
  }, []);

  const pages = useMemo(() => {
    if (!data) return null;
    const lastMonth = distinctValues(data.length, "month")
      .filter((m) => m.startsWith(String(YEAR)))
      .sort()
      .at(-1);
    const lastQuarter = distinctValues(data.quarterly.overall, "quarter")
      .filter((q) => q <= `${YEAR}-12-31`)
      .sort()
      .at(-1);
    const through = {
      monthName: formatMonthLabel(lastMonth).split(" ")[0],
      lastQuarterLabel: formatQuarterLabel(lastQuarter),
    };

    const scope = (rows, pop, sel) => filterRows(rows, { populationSegment: pop.key, dimension: sel.dimension, category: sel.category });
    const lastN = (rows, n) => rows.filter((r) => r.month <= `${YEAR}-12-31`).sort((a, b) => a.month.localeCompare(b.month)).slice(-n);

    // Length panels for one (population, selection), plus their own max, so
    // a YYA/All Population pair can share one y-scale.
    const lengthFor = (pop, sel) => {
      const still = lastN(scope(data.length, pop, sel), 24);
      const byExit = scope(data.lengthByExit, pop, sel);
      const panelRows = {
        still_active: still,
        permanently_housed: lastN(byExit.filter((r) => r.exit_type === "permanently_housed"), 24),
        inactive: lastN(byExit.filter((r) => r.exit_type === "inactive"), 24),
        aged_out: pop.key === "yya" ? lastN(byExit.filter((r) => r.exit_type === "aged_out"), 24) : [],
      };
      const vals = Object.values(panelRows)
        .flat()
        .filter((r) => !r.suppression_marker)
        .map((r) => r.p75_days ?? r.median_days)
        .filter((v) => v != null);
      return { panelRows, max: vals.length ? Math.max(...vals) : 0 };
    };

    const out = [];
    for (const st of stations) {
      for (const sel of SELECTIONS) {
        const pairLength = st === "length" ? POPULATIONS.map((p) => lengthFor(p, sel)) : null;
        const pairMax = pairLength ? Math.max(...pairLength.map((l) => l.max)) * 1.1 || 1 : null;
        POPULATIONS.forEach((pop, pi) => {
          const quarterly = scope(data.quarterly[sel.dimension] ?? [], pop, sel);
          const period = buildFlowPeriod(scope(data.flowYearly, pop, sel), [], [], { year: YEAR });
          const returns = scope(data.returnCohorts, pop, sel)
            .filter((r) => r.window_complete && Number(r.exit_quarter.slice(0, 4)) <= YEAR)
            .sort((a, b) => a.exit_quarter.localeCompare(b.exit_quarter))
            .slice(-8);
          const headline = scope(data.lengthHeadline, pop, sel).find((r) => r.year === YEAR);
          out.push({
            key: `${st}-${sel.dimension}-${pop.key}`,
            station: st,
            pop,
            sel,
            body:
              st === "overview" ? (
                <OverviewBody population={pop} period={period} quarterly={quarterly} />
              ) : st === "inflow" ? (
                <InflowBody population={pop} period={period} quarterly={quarterly} />
              ) : st === "outflow" ? (
                <OutflowBody population={pop} quarterly={quarterly} returns={returns} />
              ) : (
                <LengthBody population={pop} headline={headline} panelRows={pairLength[pi].panelRows} yMax={pairMax} />
              ),
          });
        });
      }
    }
    return { out, through };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  useEffect(() => {
    if (pages) document.body.dataset.printReady = "true";
  }, [pages]);

  if (error) return <p>Couldn't load data: {error.message}</p>;
  if (!pages) return <p>Loading…</p>;

  return (
    <div className="print-root">
      {pages.out.map((p) => (
        <section className={`print-page print-page--${p.station}`} key={p.key}>
          <PageHeader station={p.station} population={p.pop} selection={p.sel} through={pages.through} />
          <div className="print-body">{p.body}</div>
          <PageFooter station={p.station} through={pages.through} />
        </section>
      ))}
    </div>
  );
}
