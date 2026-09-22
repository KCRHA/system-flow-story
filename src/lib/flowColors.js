// Shared flow_type -> color mapping for the flow charts' inflow/outflow
// reasons, keyed to the KCRHA categorical palette in styles/tokens.css.
//
// permanently_housed deliberately uses chart-3 (light green), not chart-2 —
// chart-2 (teal) is reserved for "Active" everywhere in this app (KpiCard's
// hero number, the sankey's Active/Start/Remains nodes). On the sankey
// chart specifically, Permanently Housed sits immediately next to the
// Active nodes, so sharing teal there would read as the same category
// instead of two adjacent ones. chart-3 is the next color in
// tokens.css's approved priority order after chart-1/chart-2 (both
// already spoken for by Newly Homeless/Active), and still reads as a
// positive outcome.
export const FLOW_COLORS = {
  newly_homeless: "var(--chart-1)",
  return_from_housed: "var(--chart-5)",
  return_from_inactive: "var(--chart-6)",
  permanently_housed: "var(--chart-3)",
  inactive: "var(--chart-11)",
  deceased: "var(--chart-gray, #404040)",
  // Aged out of the YYA population (see build_flow.py's
  // _partition_by_individual) — chart-4 (yellow), the next unused color in
  // tokens.css's priority order. Deliberately not chart-11 (inactive)'s
  // muted blue-gray or deceased's neutral gray: aging out isn't a negative
  // outcome the way those are, it's a system-eligibility transition, so it
  // gets a color of its own rather than borrowing one that reads as "bad."
  aged_out: "var(--chart-4)",
};
