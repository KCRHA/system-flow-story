import FlowScrubberChart, {
  INFLOW_REASONS,
  OUTFLOW_REASONS,
  INFLOW_LABELS,
  OUTFLOW_LABELS,
  ACTIVE_COLOR,
  ACTIVE_LABEL,
} from "./FlowScrubberChart.jsx";
import { FLOW_COLORS } from "../../lib/flowColors.js";
import ChartLegend from "../ChartLegend.jsx";

export default function FlowScrubberControls({ monthlySteps, activeIndex, unitSize, fieldSize, onChange }) {
  // The chart's own legend is drawn inside its SVG viewBox, so it scales
  // down (and becomes unreadable) along with everything else on a narrow
  // mobile screen. This renders the same legend as normal-sized HTML.
  const legendItems = [
    ...INFLOW_REASONS.map((r) => ({ color: FLOW_COLORS[r], label: INFLOW_LABELS[r] })),
    { color: ACTIVE_COLOR, label: ACTIVE_LABEL },
    ...OUTFLOW_REASONS.map((r) => ({ color: FLOW_COLORS[r], label: OUTFLOW_LABELS[r] })),
  ];

  return (
    <div>
      <div className="flow-scrubber-controls">
        <button type="button" disabled={activeIndex === 0} onClick={() => onChange(activeIndex - 1)}>
          ‹ Prev
        </button>
        <input
          type="range"
          min={0}
          max={monthlySteps.length - 1}
          value={activeIndex}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        <button
          type="button"
          disabled={activeIndex === monthlySteps.length - 1}
          onClick={() => onChange(activeIndex + 1)}
        >
          Next ›
        </button>
      </div>
      <FlowScrubberChart
        monthlySteps={monthlySteps}
        activeIndex={activeIndex}
        direction={null}
        unitSize={unitSize}
        fieldSize={fieldSize}
      />
      <ChartLegend items={legendItems} />
    </div>
  );
}
