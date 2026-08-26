// Shared flow_type -> color mapping for the flow scrubber's inflow/outflow
// reasons, keyed to the KCRHA categorical palette in styles/tokens.css.
export const FLOW_COLORS = {
  newly_homeless: "var(--chart-1)",
  return_from_housed: "var(--chart-5)",
  return_from_inactive: "var(--chart-6)",
  permanently_housed: "var(--chart-2)",
  inactive: "var(--chart-11)",
  deceased: "var(--chart-gray, #404040)",
};
