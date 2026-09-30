import { useEffect, useRef } from "react";
import { createTooltip } from "../lib/tooltip.js";

// `trendDirection` ("up"/"down"/"flat"/null) is this month vs. the prior
// month for this specific card, computed by the caller (see OutflowSection's
// trendDirectionFor) — null when there's no prior month to compare against
// at all; "flat" when there is one and the value hasn't changed.
// `goodDirection` ("up"/"down"/null) says which direction is desirable for
// this specific metric: the arrow renders "good" (green) when trendDirection
// matches it, "bad" (red) when it's the opposite. `goodDirection: null`
// (Deceased) opts a card out of that judgment entirely — the arrow still
// shows which way the number moved, just always in neutral gray, since
// color-coding a rise or fall in deaths as "good"/"bad" isn't appropriate.
// "flat" is always neutral gray too, regardless of goodDirection — no
// change isn't a "good" or "bad" outcome for any metric.
// `marker` ("*"/"**") means this cell was suppressed — show it instead of a
// number, never fall back to displaying 0.
// `percent` (e.g. "12.3%"), when given, renders parenthetically right after
// the value — the caller (OutflowSection's percentOfExperienced) is
// responsible for withholding it whenever either side of the ratio is
// suppressed or the denominator is zero, so a marker never needs to be
// duplicated here.
// `trendTooltip` (e.g. "This is a 12% increase from 8,404 in Q1 2026."), when
// given, renders on hover over the arrow using the same styled tooltip
// every D3 chart in this app uses (see lib/tooltip.js) — not the browser's
// native `title` tooltip, which looks inconsistent next to them.
export default function KpiCard({ label, value, marker, percent, trendDirection, trendTooltip, goodDirection }) {
  const tone = !trendDirection
    ? null
    : trendDirection === "flat" || goodDirection == null
    ? "neutral"
    : trendDirection === goodDirection
    ? "good"
    : "bad";
  const tooltipRef = useRef(null);

  // One tooltip element per card instance, appended to document.body (not
  // scoped to this card's own DOM, since `position: fixed` doesn't need
  // it) — created once on mount and torn down on unmount, unlike the D3
  // charts' createTooltip/clearTooltip pairing, which instead rebuilds its
  // tooltip on every render alongside the rest of the chart it clears.
  useEffect(() => {
    tooltipRef.current = createTooltip(document.body);
    return () => tooltipRef.current?.destroy();
  }, []);

  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {marker ? (
          <span className="suppressed-cell" title="Data suppressed (small cell)">{marker}</span>
        ) : (
          <>
            {value}
            {percent && <span className="kpi-percent">({percent})</span>}
          </>
        )}
        {!marker && tone && (
          <span
            className={`kpi-direction ${tone}`}
            onMouseEnter={(event) => trendTooltip && tooltipRef.current?.show(`<div>${trendTooltip}</div>`, event)}
            onMouseMove={(event) => trendTooltip && tooltipRef.current?.move(event)}
            onMouseLeave={() => tooltipRef.current?.hide()}
          >
            {trendDirection === "up" ? "▲" : trendDirection === "down" ? "▼" : "●"}
          </span>
        )}
      </div>
    </div>
  );
}
