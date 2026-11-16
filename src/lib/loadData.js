const BASE = import.meta.env.BASE_URL;

// A cell can carry a suppression_marker for two different reasons: an
// ordinary small-cell mask ("*"/"**" — see the pipeline's suppression.py)
// or this one, meaning the pipeline couldn't safely disaggregate this
// (period, population, dimension, category) combination at all — every
// category in that slice was too small to protect individually, so the
// whole scope was blanked together rather than left as a partially-masked,
// still-derivable set of numbers. Distinct from the small-cell markers so
// the frontend can show a dedicated "population too small" message instead
// of routing it through the ordinary per-cell suppressed-value display.
export const INSUFFICIENT_POPULATION_MARKER = "insufficient_population";

// Matches PRIMARY_SUPPRESSION_MARKER/SECONDARY_SUPPRESSION_MARKER in
// pipeline/suppression.py. Primary ("*") means this cell's own true count
// is small; secondary ("**") means an otherwise-showable cell was hidden
// too, to keep a nearby primary-suppressed cell from being back-calculated
// — see FlowSankeyChart, which renders a node's secondary-suppressed links
// (if any are present at that node) expanded to fill whatever's left of
// its true total, with primary-suppressed links staying at a small fixed
// sliver; when a node has primary-suppressed links but no secondary ones,
// the primary links themselves take on that expanding role instead, so a
// visual gap doesn't reappear just because that particular node didn't
// need secondary suppression.
export const PRIMARY_SUPPRESSION_MARKER = "*";
export const SECONDARY_SUPPRESSION_MARKER = "**";

/** Plain-language hover text for a hidden cell, by its marker — shared by
 * every chart tooltip and KPI card so the wording stays the same everywhere. */
export function suppressedMessage(marker) {
  if (marker === INSUFFICIENT_POPULATION_MARKER) return "Population too small to safely display for this combination";
  if (marker === SECONDARY_SUPPRESSION_MARKER) return "Hidden so a nearby small number can't be calculated";
  return "Small number hidden to preserve client privacy";
}

async function fetchJson(path) {
  const res = await fetch(`${BASE}data/${path}`);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export async function loadDashboardData() {
  const [
    flowYearly,
    length,
    lengthByExit,
    lengthHeadline,
    lengthHeadlineMonthly,
    lengthHeadlineQuarterly,
    returnCohorts,
    capacity,
    capacityQuarterly,
    capacityYearly,
    flowYtdPrior,
    lengthHeadlineYtdPrior,
  ] = await Promise.all([
    fetchJson("dashboard_flow_yearly.json"),
    // dashboard_flow_quarterly is NOT fetched here — it's pre-split one
    // file per dimension now (~1-15MB each, not one ~110MB blob covering
    // every dimension at once — see pipeline/export.py's
    // _write_quarterly_flow_split), and App.jsx only ever needs the
    // currently-selected demographic dimension's rows. See
    // loadQuarterlyFlowForDimension below, fetched lazily per dimension
    // the same way loadMonthlyFlowForYear already is per year.
    fetchJson("dashboard_length_monthly.json"),
    fetchJson("dashboard_length_by_exit_monthly.json"),
    fetchJson("dashboard_length_headline_yearly.json"),
    // Finer-grain siblings of dashboard_length_headline_yearly, for
    // LengthSection's headline KPI card to use when a reader drills into a
    // specific month/quarter elsewhere on the page — not published by every
    // pipeline run yet, so a missing file resolves to [] (the card falls
    // back to the year view) instead of breaking the whole page load, same
    // as loadMonthlyFlowForYear's own empty-is-fine fallback below.
    fetchJson("dashboard_length_headline_monthly.json").catch(() => []),
    fetchJson("dashboard_length_headline_quarterly.json").catch(() => []),
    fetchJson("dashboard_return_cohorts.json"),
    fetchJson("dashboard_capacity_monthly.json"),
    fetchJson("dashboard_capacity_quarterly.json"),
    fetchJson("dashboard_capacity_yearly.json"),
    // The prior year capped to the current partial year's months (e.g.
    // Jan-Oct 2025 next to Jan-Oct 2026), for the full-year view's trend
    // pills — see pipeline/export.py. Empty once the current year is
    // complete; a missing file resolves to [] the same way.
    fetchJson("dashboard_flow_ytd_prior.json").catch(() => []),
    fetchJson("dashboard_length_headline_ytd_prior.json").catch(() => []),
  ]);
  return {
    flowYtdPrior,
    lengthHeadlineYtdPrior,
    flowYearly,
    length,
    lengthByExit,
    lengthHeadline,
    lengthHeadlineMonthly,
    lengthHeadlineQuarterly,
    returnCohorts,
    capacity,
    capacityQuarterly,
    capacityYearly,
  };
}

// dashboard_flow_monthly is pre-split by calendar year (see
// pipeline/export.py's _write_monthly_flow_split) — one year's worth of
// rows (~35-45MB) is still a lot to fetch on every year switch, so App.jsx
// caches each year's rows after the first fetch rather than calling this
// again. A year with no export file (outside the pipeline's export window)
// resolves to [] instead of throwing, matching MonthPills' existing
// empty-is-fine rendering.
export async function loadMonthlyFlowForYear(year) {
  return fetchJson(`dashboard_flow_monthly_${year}.json`).catch(() => []);
}

// dashboard_flow_quarterly's sibling of loadMonthlyFlowForYear above, split
// by dimension instead of by year (see pipeline/export.py's
// _write_quarterly_flow_split for why the split key differs: OutflowSection
// always wants one dimension's full multi-year history, never one year's
// worth of every dimension). App.jsx fetches "overall" eagerly (the default
// demographic selection) and every other dimension only once a reader
// actually picks it, caching each after the first fetch the same way
// App.jsx's monthlyFlowByYear already does.
export async function loadQuarterlyFlowForDimension(dimension) {
  return fetchJson(`dashboard_flow_quarterly_${dimension}.json`).catch(() => []);
}

export function filterRows(rows, { populationSegment, dimension, category, month, flowType, projectType }) {
  return rows.filter((row) => {
    if (populationSegment && row.population_segment !== populationSegment) return false;
    if (dimension && row.dimension !== dimension) return false;
    if (category && row.category !== category) return false;
    if (month && row.month !== month) return false;
    if (flowType && row.flow_type !== flowType) return false;
    if (projectType && row.project_type !== projectType) return false;
    return true;
  });
}

export function distinctValues(rows, key) {
  return [...new Set(rows.map((row) => row[key]))];
}

// Suppressed cells carry a "*" (primary) or "**" (secondary/complementary)
// marker instead of a count. Never treat a suppressed cell as 0 — 0 is a
// real, reportable value; suppressed means "we withheld this number."
// deceased_in_inactive rows published as a band also carry count_low/
// count_high (see lib/deceased.js); low/high carry it through.
export function resolveCell(row, countKey = "count") {
  const marker = row?.suppression_marker ?? null;
  const hasBand = countKey === "count" && marker && row?.count_low != null && row?.count_high != null;
  return {
    value: marker ? null : row?.[countKey] ?? 0,
    marker,
    low: hasBand ? row.count_low : null,
    high: hasBand ? row.count_high : null,
  };
}
