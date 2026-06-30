/**
 * Expects rows shaped like:
 *   { category, value, ...dimension columns }
 * Sums `value` per category after filtering, sorted descending.
 */
export function toBarChart(rows) {
  const totals = new Map();
  for (const row of rows) {
    totals.set(row.category, (totals.get(row.category) || 0) + Number(row.value));
  }
  return Array.from(totals, ([category, value]) => ({ category, value })).sort(
    (a, b) => b.value - a.value
  );
}
