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

// Optional, off unless the URL has ?hostData: when this page is framed by a page
// on the same site, it asks that page for each data file instead of fetching
// data/. It posts {type: "sfs:get", id, path} to its parent, which answers
// {type: "sfs:file", id, ok, data} or {..., ok: false, error}. Files are asked
// for only when needed, the same as fetching. With no answer within 60 seconds
// it fetches data/ as usual. Lets a site serve the files from its own API (for
// example, per signed-in user) without publishing them as static files.
const hostData =
  typeof window !== "undefined" && window.parent !== window && new URLSearchParams(window.location.search).has("hostData");
const pending = new Map();
let nextId = 0;
if (hostData) {
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || e.origin !== window.location.origin) return;
    const m = e.data;
    if (m?.type !== "sfs:file" || !pending.has(m.id)) return;
    const { resolve, reject, timer } = pending.get(m.id);
    pending.delete(m.id);
    clearTimeout(timer);
    if (m.ok) resolve(m.data);
    else reject(new Error(`Failed to load ${m.path ?? "file"}: ${m.error ?? "not provided"}`));
  });
}
function fromHost(path) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); resolve(undefined); }, 60000);
    pending.set(id, { resolve, reject, timer });
    window.parent.postMessage({ type: "sfs:get", id, path }, window.location.origin);
  });
}

async function fetchJson(path) {
  if (hostData) {
    const data = await fromHost(path);
    if (data !== undefined) return data;
  }
  const res = await fetch(`${BASE}data/${path}`);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

export async function loadDashboardData() {
  const [flowYearly, flowQuarterly, length, returnCohorts, capacity, capacityQuarterly, capacityYearly] = await Promise.all([
    fetchJson("dashboard_flow_yearly.json"),
    fetchJson("dashboard_flow_quarterly.json"),
    fetchJson("dashboard_length_monthly.json"),
    fetchJson("dashboard_return_cohorts.json"),
    fetchJson("dashboard_capacity_monthly.json"),
    fetchJson("dashboard_capacity_quarterly.json"),
    fetchJson("dashboard_capacity_yearly.json"),
  ]);
  return { flowYearly, flowQuarterly, length, returnCohorts, capacity, capacityQuarterly, capacityYearly };
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
