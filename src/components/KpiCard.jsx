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
export default function KpiCard({ label, value, marker, trendDirection, goodDirection }) {
  const tone = !trendDirection ? null : goodDirection == null ? "neutral" : trendDirection === goodDirection ? "good" : "bad";
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {marker ? <span className="suppressed-cell" title="Data suppressed (small cell)">{marker}</span> : value}
        {!marker && tone && (
          <span className={`kpi-direction ${tone}`}>{trendDirection === "up" ? "▲" : "▼"}</span>
        )}
      </div>
    </div>
  );
}
