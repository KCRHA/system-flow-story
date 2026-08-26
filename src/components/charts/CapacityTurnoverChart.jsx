import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";

const PROJECT_TYPE_LABELS = { ph: "Permanent Housing", th: "Transitional Housing", es: "Emergency Shelter", rrh: "Rapid Re-Housing" };

// "Turnover" alone doesn't say which direction is good — it flips
// depending on what the program is for. Split into two labeled groups so
// the framing is explicit rather than implied by raw bar length.
const GROUPS = [
  { key: "stability", title: "Stability-Focused — lower is better", types: ["ph"], color: "var(--chart-6)" },
  { key: "transitional", title: "Transitional — higher is better", types: ["th", "es", "rrh"], color: "var(--chart-2)" },
];

const GROUP_HEADER_H = 20;
const ROW_H = 44;
const ANNOTATION_DY = 30;
const GROUP_GAP = 18;

/**
 * rows: [{ project_type, pct_exited, households_per_unit, exited, active }]
 * for the selected year, from dashboard_capacity_yearly.json.
 *
 * pct_exited (share of everyone served this year who also exited within
 * it) drives the bar, on one shared 0-100% scale across both groups —
 * unlike a raw household count, a percentage is already normalized, so
 * there's no need for Emergency Shelter's larger volume to get its own
 * scale the way the old total-households version did.
 *
 * households_per_unit (average households served per unit this year) is
 * annotated under each row rather than its own chart — it's a read on
 * *how fast* a unit cycles (e.g. one ES unit with ~2-month stays reads
 * as ~6/year), a different question from turnover rate, but naturally
 * paired with it per project type.
 */
export default function CapacityTurnoverChart({ rows, width = 640 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!rows?.length) return;
    const byType = Object.fromEntries(rows.map((d) => [d.project_type, d]));
    const margin = { top: 8, right: 60, bottom: 10, left: 160 };
    const innerW = width - margin.left - margin.right;

    let cursorY = 0;
    const groupLayout = GROUPS.map((grp) => {
      const top = cursorY;
      cursorY += GROUP_HEADER_H + grp.types.length * ROW_H + GROUP_GAP;
      return { ...grp, top };
    });
    const height = margin.top + cursorY - GROUP_GAP + margin.bottom;

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    // One shared scale across both groups — pct_exited is already a
    // normalized 0-100% figure, so (unlike raw household counts) there's
    // no volume disparity between project types that needs correcting for.
    const x = d3.scaleLinear().domain([0, 1]).range([0, innerW]);

    groupLayout.forEach((grp) => {
      g.append("text")
        .attr("x", 0)
        .attr("y", grp.top + 12)
        .attr("font-size", 12)
        .attr("font-weight", 600)
        .attr("fill", "var(--text-navy)")
        .text(grp.title);

      grp.types.forEach((type, i) => {
        const rowY = grp.top + GROUP_HEADER_H + i * ROW_H;
        const d = byType[type];
        const hasRate = d?.pct_exited != null;

        g.append("text")
          .attr("x", -10)
          .attr("y", rowY + ROW_H / 2 - ANNOTATION_DY / 2)
          .attr("dy", "0.35em")
          .attr("text-anchor", "end")
          .attr("font-size", 12)
          .attr("fill", "var(--text-dark)")
          .text(PROJECT_TYPE_LABELS[type] || type);

        if (hasRate) {
          // pct_exited is structurally bounded to [0, 1] (active =
          // exited + still-active-at-year-end, by definition — see
          // build_capacity.py), so this only guards against the rare
          // source-data inconsistency (~0.06% of program-years checked)
          // rather than an expected case — clamp the bar's width so a
          // stray one can't overflow the chart, but keep showing the
          // true (uncapped) percentage in the label.
          const barPct = Math.min(d.pct_exited, 1);
          const onHover = (event) => {
            tooltip.show(
              `<div style="font-weight:600">${PROJECT_TYPE_LABELS[type] || type}</div>` +
                `<div>${d.exited.toLocaleString()} exited / ${d.active.toLocaleString()} active</div>`,
              event
            );
          };
          const rowHover = (sel) =>
            sel.on("mouseenter", onHover).on("mousemove", (event) => tooltip.move(event)).on("mouseleave", () => tooltip.hide());

          rowHover(
            g
              .append("rect")
              .attr("x", 0)
              .attr("y", rowY + 4)
              .attr("height", ROW_H - ANNOTATION_DY - 8)
              .attr("width", 0)
              .attr("fill", grp.color)
          ).transition().duration(400).attr("width", x(barPct));

          rowHover(
            g
              .append("text")
              .attr("x", x(barPct) + 8)
              .attr("y", rowY + (ROW_H - ANNOTATION_DY) / 2)
              .attr("dy", "0.35em")
              .attr("font-size", 12)
              .attr("fill", "var(--text-dark)")
              .text(`${(d.pct_exited * 100).toFixed(0)}%`)
          );
        } else {
          g.append("text")
            .attr("x", 0)
            .attr("y", rowY + (ROW_H - ANNOTATION_DY) / 2)
            .attr("dy", "0.35em")
            .attr("font-size", 12)
            .attr("fill", "var(--gray-mid)")
            .attr("font-style", "italic")
            .text("No data");
        }

        g.append("text")
          .attr("x", 0)
          .attr("y", rowY + ROW_H - ANNOTATION_DY / 2 + 2)
          .attr("dy", "0.35em")
          .attr("font-size", 11)
          .attr("fill", "var(--text-gray)")
          .text(
            d?.households_per_unit != null
              ? `≈${d.households_per_unit.toFixed(1)} households served per unit this year`
              : "No unit-throughput data"
          );
      });
    });

    g.append("g")
      .attr("transform", `translate(0,${cursorY - GROUP_GAP})`)
      .call(d3.axisBottom(x).ticks(5, "%"))
      .attr("font-size", 10)
      .call((axisG) => axisG.select(".domain").remove());
  }, [rows, width]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
