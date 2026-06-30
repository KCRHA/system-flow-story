/**
 * Filters dataset rows against a selections object, e.g.
 * { region: "South King County", quarter: "2026-Q2" }
 *
 * A selection value of "" or "All" (anything in IGNORE_VALUES) means
 * "don't filter on this dimension" — that's what makes "All regions"
 * work as a dropdown option for free.
 */
const IGNORE_VALUES = new Set(['', 'All', 'all']);

export function filterRows(rows, selections) {
  const activeKeys = Object.keys(selections).filter(
    (k) => !IGNORE_VALUES.has(selections[k])
  );
  if (activeKeys.length === 0) return rows;
  return rows.filter((row) => activeKeys.every((k) => row[k] === selections[k]));
}
