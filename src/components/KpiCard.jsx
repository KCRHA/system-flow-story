// `trendDirection` ("up"/"down"/null) is this month vs. the prior month for
// this specific card, computed by the caller (see OutflowSection's
// trendDirectionFor) — null when there's no prior month to compare against,
// or either side is suppressed/missing.
// `goodDirection` ("up"/"down"/null) says which direction is desirable for
// this specific metric: the arrow renders "good" (green) when trendDirection
// matches it, "bad" (red) when it's the opposite. `goodDirection: null`
// (Deceased) opts a card out of that judgment entirely — the arrow still
// shows which way the number moved, just always in neutral gray, since
// color-coding a rise or fall in deaths as "good"/"bad" isn't appropriate.
// `marker` ("*"/"**") means this cell was suppressed — show it instead of a
// number, never fall back to displaying 0.
// `percent` (e.g. "12.3%"), when given, renders parenthetically right after
// the value — the caller (OutflowSection's percentOfExperienced) is
// responsible for withholding it whenever either side of the ratio is
// suppressed or the denominator is zero, so a marker never needs to be
// duplicated here.
export default function KpiCard({ label, value, marker, percent, trendDirection, goodDirection }) {
  const tone = !trendDirection ? null : goodDirection == null ? "neutral" : trendDirection === goodDirection ? "good" : "bad";
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
          <span className={`kpi-direction ${tone}`}>{trendDirection === "up" ? "▲" : "▼"}</span>
        )}
      </div>
    </div>
  );
}
