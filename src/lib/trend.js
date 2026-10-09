// Shared by any section rendering a KpiCard with a trend pill (currently
// OutflowSection and LengthSection) — a cell's direction/text vs. a prior
// period, in the {value, marker} shape every dashboard_* suppression table
// already uses.

// "up"/"down"/"flat" if `current` is (or must be) higher/lower/equal to
// `previous`; null if there's no previous period to compare against at all.
//
// Suppression only ever hides a NONZERO value below the threshold (see
// suppression.py) — a true zero is never suppressed. So a suppressed
// previous cell's real value is guaranteed to be in [1, threshold - 1],
// always > 0, even without knowing the exact number. A visible
// (marker-free) current value is therefore guaranteed higher than that
// ONLY if it's itself nonzero (which, being unsuppressed, means it's at
// or above the threshold); a visible current value of exactly 0 is below
// every possible hidden previous value, i.e. "down". The reverse (current
// suppressed) never needs handling here: KpiCard doesn't render an arrow
// next to a suppressed current value at all.
export function trendDirectionFor(current, previous) {
  if (!current || !previous || current.marker) return null;
  if (previous.marker) return current.value > 0 ? "up" : "down";
  if (current.value > previous.value) return "up";
  if (current.value < previous.value) return "down";
  return "flat";
}

// Short, always-visible text for a KPI card's trend pill (see KpiCard's
// `trendText` prop) — covers every case trendDirectionFor above can produce
// an arrow for, condensed to pill length rather than a full sentence:
// - both sides known and different: an exact percent ("12% vs. Q1 2026").
// - both sides known and equal: called out as unchanged, not a 0% change.
// - a real (non-suppressed) previous value of 0: "New", no percent — percent
//   change from zero is undefined.
// - a suppressed previous value: no percent, naming that side as suppressed
//   rather than implying a precise number (the exact prior count isn't
//   knowable, only that it's under the suppression threshold — see
//   trendDirectionFor's comment on why direction alone is still safe to
//   state).
export function trendPillText(current, previous, previousLabel) {
  if (!current || !previous || current.marker || !previousLabel) return null;
  if (previous.marker) return `vs. fewer than 11 in ${previousLabel}`;
  if (current.value === previous.value) return `No change vs. ${previousLabel}`;
  if (!previous.value) return `New vs. ${previousLabel}`;
  const percent = Math.round((Math.abs(current.value - previous.value) / previous.value) * 100);
  return `${percent}% vs. ${previousLabel}`;
}
