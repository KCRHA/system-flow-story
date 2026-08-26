export function LegendSwatch({ color, label }) {
  return (
    <span className="chart-legend-item">
      <span className="chart-legend-dot" style={{ background: color }} />
      {label}
    </span>
  );
}

/** items: [{ color, label }] */
export default function ChartLegend({ items }) {
  return (
    <div className="chart-legend">
      {items.map((item) => (
        <LegendSwatch key={item.label} color={item.color} label={item.label} />
      ))}
    </div>
  );
}
