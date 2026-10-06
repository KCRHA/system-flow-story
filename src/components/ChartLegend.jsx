// `kind` picks the swatch shape: "dot" (default, a filled circle — e.g. a
// category color), "line" (a short solid stroke — a trend line), "dashed"
// (a short dashed stroke — a reference line), or "ring" (a hollow
// circle — a marker outline, like a highlighted point) — see
// HomelessnessTrendChart for one legend mixing all four.
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
