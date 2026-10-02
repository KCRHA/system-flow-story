import InfoIcon from "./InfoIcon.jsx";

// `trendDirection` ("up"/"down"/"flat"/null) is this period vs. the prior
// one for this specific card, computed by the caller (see OutflowSection's
// trendDirectionFor) — null when there's no prior period to compare against
// at all; "flat" when there is one and the value hasn't changed.
// `goodDirection` ("up"/"down"/null) says which direction is desirable for
// this specific metric: the pill renders "good" (green) when trendDirection
// matches it, "bad" (orange) when it's the opposite. `goodDirection: null`
// (Deceased, Inactive) opts a card out of that judgment entirely — the pill
// still shows which way the number moved, just always in neutral gray,
// since color-coding a rise or fall as "good"/"bad" isn't appropriate for
// those terms. "flat" is always neutral gray too, regardless of
// goodDirection — no change isn't a "good" or "bad" outcome for any metric.
// Reuses the same good/bad/neutral -> positive/concerning/neutral chip
// classes as the arrow-legend above these cards, so the pill's colors are
// the ones that legend already describes.
// `marker` ("*"/"**") means this cell was suppressed — show it instead of a
// number, never fall back to displaying 0.
// `percent` (e.g. "12%"), when given, renders as plain text ("12% of
// total") to the right of the value — the caller (OutflowSection's
// percentOfExperienced) is responsible for withholding it whenever either
// side of the ratio is suppressed or the denominator is zero, so a marker
// never needs to be duplicated here.
// `description`, when given, is a short plain-language line shown directly
// under the label (not on hover) — used for the outflow cards only (see
// OutflowSection's KPI_CARD_INFO), where the mockup calls for the
// definition to always be visible rather than tucked behind the info icon.
// `trendText` (e.g. "12% vs. Q1 2026"), when given alongside a non-null
// tone, renders inside the trend pill at the bottom of the card (top-right
// for the hero row — see .kpi-row-hero .kpi-trend-pill) — always visible,
// not a hover tooltip.
// `info` ({ title, body, linkHref, linkLabel }), when given, renders a small
// "ⓘ" next to the label that opens a dark popover defining this specific
// term on hover (see InfoIcon's "dark" variant) — distinct from the
// section header's own "Show definitions" glossary, which lists every term
// at once rather than one at a time next to its card.
export default function KpiCard({ label, value, marker, percent, description, trendDirection, trendText, goodDirection, info }) {
  const tone = !trendDirection
    ? null
    : trendDirection === "flat" || goodDirection == null
    ? "neutral"
    : trendDirection === goodDirection
    ? "good"
    : "bad";
  const pillClass = tone === "good" ? "positive" : tone === "bad" ? "concerning" : "neutral";

  return (
    <div className="kpi-card">
      <div className="kpi-label-row">
        <div className="kpi-label">{label}</div>
        {info && (
          <InfoIcon label={`About ${label}`} variant="dark">
            <p className="info-icon-popover-title">{info.title}</p>
            <p>{info.body}</p>
            {info.linkHref && (
              <p>
                <a href={info.linkHref} target="_blank" rel="noreferrer">
                  {info.linkLabel ?? "See full definitions"}
                </a>
              </p>
            )}
          </InfoIcon>
        )}
      </div>
      {description && <p className="kpi-description">{description}</p>}
      <div className="kpi-value-row">
        {marker ? (
          <span className="suppressed-cell" title="Data suppressed (small cell)">{marker}</span>
        ) : (
          <>
            <span className="kpi-value">{value}</span>
            {percent && <span className="kpi-percent-total">{percent} of total</span>}
          </>
        )}
      </div>
      {!marker && tone && trendText && (
        <span className={`kpi-trend-pill legend-chip ${pillClass}`}>
          <span aria-hidden="true">{trendDirection === "up" ? "▲" : trendDirection === "down" ? "▼" : "●"}</span>
          {" "}
          {trendText}
        </span>
      )}
    </div>
  );
}
