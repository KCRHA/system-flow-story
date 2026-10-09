// `kind` picks the swatch shape: "dot" (default, a filled circle — e.g. a
// category color), "line" (a short solid stroke — a trend line), "dashed"
// (a short dashed stroke — a reference line), "ring" (a hollow
// circle — a marker outline, like a highlighted point), or "band" (a small
// filled rectangle — a shaded range, like LengthChart's p25-p75 band) — see
// HomelessnessTrendChart for one legend mixing dot/line/dashed/ring.
export function LegendSwatch({ color, label, kind = "dot" }) {
  return (
    <span className="chart-legend-item">
      <span className={`chart-legend-swatch chart-legend-swatch-${kind}`} style={{ "--swatch-color": color }} />
      {label}
    </span>
  );
}

/** items: [{ color, label, kind? }] */
export default function ChartLegend({ items }) {
  return (
    <div className="chart-legend">
      {items.map((item) => (
        <LegendSwatch key={item.label} color={item.color} label={item.label} kind={item.kind} />
      ))}
    </div>
  );
}
