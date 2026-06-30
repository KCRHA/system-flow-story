/**
 * Loads a long-format dataset from /public/data. All datasets share this
 * shape: an array of row objects, each tagged with dimension columns
 * (region, program_type, quarter, etc.) plus whatever value/category
 * columns the chart type needs. See README.md "Adding a new chart".
 *
 * Files live in /public/data so Vite copies them verbatim to the build
 * output regardless of how many there are or what they're named —
 * unlike importing them, which requires Vite to know every filename
 * ahead of time.
 */
export async function loadDataset(filename) {
  const url = `${import.meta.env.BASE_URL}data/${filename}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load dataset: ${filename} (${res.status})`);
  }
  return res.json();
}

/**
 * Returns the distinct values present for a given column across a dataset —
 * used to auto-populate filter dropdown options from the data itself, so
 * you never have to hand-maintain a list of "which regions exist."
 */
export function distinctValues(rows, column) {
  return Array.from(new Set(rows.map((r) => r[column]))).sort();
}
