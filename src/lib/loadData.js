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
// — see FlowSankeyChart, which renders the two differently (primary stays
// a small fixed sliver; secondary expands to fill whatever's left of its
// node's own true total).
export const SECONDARY_SUPPRESSION_MARKER = "**";

async function fetchJson(path) {
  const res = await fetch(`${BASE}data/${path}`);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export async function loadDashboardData() {
  const [flow, flowYearly, flowQuarterly, length, returnCohorts, capacity, capacityQuarterly, capacityYearly] = await Promise.all([
    fetchJson("dashboard_flow_monthly.json"),
    fetchJson("dashboard_flow_yearly.json"),
    fetchJson("dashboard_flow_quarterly.json"),
    fetchJson("dashboard_length_monthly.json"),
    fetchJson("dashboard_return_cohorts.json"),
    fetchJson("dashboard_capacity_monthly.json"),
    fetchJson("dashboard_capacity_quarterly.json"),
    fetchJson("dashboard_capacity_yearly.json"),
  ]);
  return { flow, flowYearly, flowQuarterly, length, returnCohorts, capacity, capacityQuarterly, capacityYearly };
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
export function resolveCell(row, countKey = "count") {
  const marker = row?.suppression_marker ?? null;
  return { value: marker ? null : row?.[countKey] ?? 0, marker };
}
