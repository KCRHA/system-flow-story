import { resolveCell } from "./loadData.js";

export const INFLOW_REASONS = ["newly_homeless", "return_from_housed", "return_from_inactive"];
export const OUTFLOW_REASONS = ["permanently_housed", "inactive", "deceased"];

// Bucket keys in display order — already_active/still_active first, so a
// caller that wants them pinned to the top of the sankey's left/right
// columns can just preserve this order (see FlowSankeyChart's nodeSort).
// aged_out sits right after still_active, matching build_flow.py's own
// OUTFLOW_BUCKET_KEYS order — it's not one of the three HUD outflow
// reasons above, just like still_active isn't; it's specific to the YYA
// population (see build_flow.py's _partition_by_individual for why an
// explicit bucket is needed there), and is always 0 for every other
// population segment.
export const INFLOW_BUCKET_KEYS = ["already_active", ...INFLOW_REASONS];
export const OUTFLOW_BUCKET_KEYS = ["still_active", "aged_out", ...OUTFLOW_REASONS];

function cellForYear(yearlyRows, year, flowType) {
  return resolveCell(
    yearlyRows.find((r) => r.year === year && r.flow_type === flowType),
    "count"
  );
}

function cellForQuarter(quarterlyRows, quarter, flowType) {
  return resolveCell(
    quarterlyRows.find((r) => r.quarter === quarter && r.flow_type === flowType),
    "count"
  );
}

/** Every calendar year present in `rows` (already scoped to one population
 * segment/dimension/category), most recent first. */
export function yearsIn(rows) {
  return [...new Set(rows.map((r) => r.month.slice(0, 4)))].map(Number).sort((a, b) => b - a);
}

/** Every quarter present in `quarterlyRows` (already scoped to one
 * population segment/dimension/category) for calendar year `year`, sorted
 * ascending. A quarter's own value is its start date ("YYYY-07-01" for Q3),
 * matching dashboard_flow_quarterly's convention (same as
 * dashboard_return_cohorts' exit_quarter) — dashboard_flow_quarterly never
 * carries a quarter whose 3 calendar months aren't all complete (see
 * build_flow_quarterly_rows), so every quarter that appears here is
 * automatically a finished one. */
export function quartersInYear(quarterlyRows, year) {
  return [...new Set(quarterlyRows.filter((r) => r.quarter.slice(0, 4) === String(year)).map((r) => r.quarter))].sort();
}

// Every number here comes straight from the pipeline's indiv_* flow_types
// (build_flow.py's _partition_by_individual) — each of the four inflow
// buckets (already active / newly homeless / return from housed / return
// from inactive) and five outflow buckets (still active / aged out [YYA
// only] / permanently housed / inactive / deceased) assigns a given
// person to exactly ONE bucket for the period, so the four inflow counts
// sum to experiencedHomelessness exactly, and so do the five outflow
// counts —
// this is a partition of individuals, not a count of episode-entry
// events. That partitioning has to happen with the whole period's
// episodes in view at once (to find each person's single earliest
// inflow / latest outflow event), which isn't something a monthly cell —
// or a sum of them — can reconstruct client-side; that's why a full-year
// or full-quarter period reads from dashboard_flow_yearly.json/
// dashboard_flow_quarterly.json's own dedicated computation rather than
// summing dashboard_flow_monthly's per-month figures.
export function buildFlowPeriod(yearlyRows, quarterlyRows, { year, quarter }) {
  const source = quarter ? quarterlyRows.filter((r) => r.quarter === quarter) : yearlyRows.filter((r) => r.year === year);
  if (!source.length) return null;

  const get = (flowType) => (quarter ? cellForQuarter(quarterlyRows, quarter, flowType) : cellForYear(yearlyRows, year, flowType));

  // Per-person (inflow bucket, outflow bucket) pairing — e.g. "of the
  // people newly homeless this period, how many were still active vs.
  // permanently housed by period's end" — lets the sankey draw a direct
  // link per combination instead of pooling everyone through one
  // "Actively Homeless" node. Keyed the same way build_flow.py's
  // indiv_flow_{inflow}_to_{outflow} flow_types are named.
  const pairs = {};
  for (const inflowKey of INFLOW_BUCKET_KEYS) {
    for (const outflowKey of OUTFLOW_BUCKET_KEYS) {
      pairs[`${inflowKey}_to_${outflowKey}`] = get(`indiv_flow_${inflowKey}_to_${outflowKey}`);
    }
  }

  return {
    period: [quarter ?? String(year)],
    startActive: get("indiv_already_active"),
    endActive: get("indiv_still_active"),
    experiencedHomelessness: get("experienced_homelessness"),
    inflow: {
      newly_homeless: get("indiv_newly_homeless"),
      return_from_housed: get("indiv_return_from_housed"),
      return_from_inactive: get("indiv_return_from_inactive"),
    },
    outflow: {
      permanently_housed: get("indiv_permanently_housed"),
      inactive: get("indiv_inactive"),
      deceased: get("indiv_deceased"),
      aged_out: get("indiv_aged_out"),
    },
    pairs,
  };
}
