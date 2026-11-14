// How many of an Inactive count are deceased (flow_type
// deceased_in_inactive, see the pipeline's suppression.apply_deceased_bands):
// 0, a band of 10 ("range", with count_low/count_high), or "withheld" (at
// least one, number withheld). Deceased itself is never shown as a count;
// it's folded into Inactive everywhere in the flow tables.
export const DECEASED_RANGE_MARKER = "range";
export const DECEASED_WITHHELD_MARKER = "withheld";

/** The italic line shown under an Inactive count, or null when it includes
 * no deceased individuals (or nothing is known). */
export function deceasedNote(cell) {
  if (!cell) return null;
  if (cell.marker === DECEASED_RANGE_MARKER && cell.low != null && cell.high != null) {
    return `This includes between ${cell.low.toLocaleString()} and ${cell.high.toLocaleString()} deceased individuals.`;
  }
  if (cell.marker === DECEASED_WITHHELD_MARKER) {
    return "This includes some deceased individuals; the number is withheld to protect privacy.";
  }
  return null;
}
