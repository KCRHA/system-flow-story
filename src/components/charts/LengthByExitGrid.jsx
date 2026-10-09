import ChartLegend from "../ChartLegend.jsx";
import LengthChart from "./LengthChart.jsx";

// Ordered the same way the grid should read: exited-to-housing first,
// exited-inactive next, then the two "hasn't exited yet" buckets. Aged Out
// is YYA-only (see population.py's filter_population YYA branch) — filtered
// out for every other population segment below, same idiom FlowSankeyChart
// uses for its own aged_out node.
const PANELS = [
  { key: "permanently_housed", label: "Permanently Housed" },
  { key: "inactive", label: "Inactive" },
  { key: "still_active", label: "Still Active" },
  { key: "aged_out", label: "Aged Out" },
];

// Shared y-axis upper bound across every panel in the row — every
// non-suppressed p75 (or median, when p75 is missing) across every
// exit-status bucket, not just one panel's own rows — so all panels plot on
// the same scale and are directly comparable, per the approved mockup. Same
// *1.1 headroom LengthChart's own per-chart fallback uses.
function sharedYMax(rowGroups) {
  const values = rowGroups
    .flat()
    .filter((r) => !r.suppression_marker)
    .map((r) => r.p75_days ?? r.median_days)
    .filter((v) => v != null);
  const max = values.length ? Math.max(...values) : 0;
  return max > 0 ? max * 1.1 : 1;
}

/** Small-multiple row of LengthChart panels, one per exit status, all on one
 * shared y-scale — see LengthSection, which scopes/windows byExitRows and
 * stillActiveRows identically (same population/demographic/year filters)
 * before passing them in here. */
export default function LengthByExitGrid({ byExitRows, stillActiveRows, populationSegment }) {
  const panels = populationSegment === "yya" ? PANELS : PANELS.filter((p) => p.key !== "aged_out");
  const panelRows = panels.map(({ key }) => (key === "still_active" ? stillActiveRows : byExitRows.filter((r) => r.exit_type === key)));
  const yMax = sharedYMax(panelRows);
  // Youth and Young Adults' extra Aged Out panel makes 4 — a 2x2 grid of
  // wider half-width panels reads better than this page's usual 3-wide row
  // plus a lone 4th panel stranded by itself on its own row below.
  const isPairLayout = panels.length === 4;

  return (
    <div>
      <ChartLegend
        items={[
          { kind: "line", color: "var(--chart-2)", label: "Median" },
          { kind: "band", color: "var(--chart-7)", label: "Middle 50% of people" },
        ]}
      />
      <div className={`length-exit-grid ${isPairLayout ? "length-exit-grid--pairs" : ""}`}>
        {panels.map(({ key, label }, i) => {
          const rows = panelRows[i];
          return (
            <div className="length-exit-panel" key={key}>
              <p className="length-panel-title">{label}</p>
              {rows.length > 0 ? (
                <LengthChart
                  rows={rows}
                  width={380}
                  height={240}
                  compact
                  yMax={yMax}
                  yAxisLabel={i === 0 ? "Days active before exiting" : null}
                  isExit={key !== "still_active"}
                />
              ) : (
                <p className="chart-note">No data for this selection.</p>
              )}
            </div>
          );
        })}
      </div>
      <p className="chart-group-caption">
        One line per month, for whoever exited to that status (or remained active) that month. Every panel uses the
        same scale. Hover or tap a point for exact values.
      </p>
    </div>
  );
}
