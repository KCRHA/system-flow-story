// Shared by any section that needs to label a quarter/month drill-down the
// same way OutflowSection's own period pills do (currently OutflowSection
// and LengthSection) — UTC-safe for the same reason sankeyData.js's
// quarterStartOfMonth is: "YYYY-MM-DD" parses as UTC midnight, but reading
// it back with local-time getters can shift the quarter/month/year for
// anyone west of UTC.

export function formatQuarterLabel(quarter) {
  const d = new Date(quarter);
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `Q${q} ${d.getUTCFullYear()}`;
}

// Same as formatQuarterLabel but without the year — for OutflowSection's
// "Months in Q2:" label above its scoped month-pills row, where the year is
// already shown elsewhere on screen.
export function quarterAbbrevLabel(quarter) {
  return `Q${Math.floor(new Date(quarter).getUTCMonth() / 3) + 1}`;
}

export function formatMonthLabel(month) {
  const d = new Date(month);
  return `${d.toLocaleString("en-US", { month: "long", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
}
