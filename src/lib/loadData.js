const BASE = import.meta.env.BASE_URL;

async function fetchJson(path) {
  const res = await fetch(`${BASE}data/${path}`);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export async function loadDashboardData() {
  const [flow, length, returnCohorts, capacity, capacityQuarterly, capacityYearly] = await Promise.all([
    fetchJson("dashboard_flow_monthly.json"),
    fetchJson("dashboard_length_monthly.json"),
    fetchJson("dashboard_return_cohorts.json"),
    fetchJson("dashboard_capacity_monthly.json"),
    fetchJson("dashboard_capacity_quarterly.json"),
    fetchJson("dashboard_capacity_yearly.json"),
  ]);
  return { flow, length, returnCohorts, capacity, capacityQuarterly, capacityYearly };
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
