import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";

const monthFormat = d3.utcFormat("%b %Y");

export const PHASES = ["newly_enrolled", "engaged", "exited"];
export const PHASE_LABELS = { engaged: "Engaged (any point in month)", newly_enrolled: "Newly Enrolled", exited: "Exited" };
export const PHASE_COLORS = { engaged: "var(--chart-2)", newly_enrolled: "var(--chart-3)", exited: "var(--chart-9)" };
const PROJECT_TYPE_LABELS = {
  outreach: "Outreach",
  emergency_shelter: "Emergency Shelter",
  transitional_housing: "Transitional Housing",
  rapid_rehousing: "Rapid Re-Housing",
  psh: "Permanent Supportive Housing",
  prevention: "Homelessness Prevention",
};

const MARGIN = { top: 8, right: 20, bottom: 26, left: 54 };
const ROW_LABEL_H = 22;
const ROW_PLOT_H = 84;
const ROW_GAP = 32;

/**
 * series: [{ project_type, points: [{ month, engaged, newly_enrolled, exited }] }]
 * where each phase value is a resolveCell() {value, marker} pair.
 *
 * One small-multiple row per project type, each with its own y-axis
 * auto-fit to that type's own range — a shared axis would flatten small
 * project types (e.g. Prevention) to a near-flat line next to a much
 * larger one (e.g. Emergency Shelter). Months share one x-axis, drawn
 * once at the bottom, so rows still align for cross-row comparison.
 */
export default function ResourceAccessChart({ series, width = 720 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!series?.length) return;
    const innerW = width - MARGIN.left - MARGIN.right;
    const rowH = ROW_LABEL_H + ROW_PLOT_H;
    const height = MARGIN.top + series.length * rowH + (series.length - 1) * ROW_GAP + MARGIN.bottom;

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    const allMonths = (series[0]?.points ?? []).map((p) => new Date(p.month));
    // scaleUtc, not scaleTime: "YYYY-MM-DD" parses as UTC midnight, and a
    // local-timezone-based scale/format (west of UTC, i.e. all of the US)
    // would silently shift every month label back by one.
    const x = d3.scaleUtc().domain(d3.extent(allMonths)).range([0, innerW]);

    const rowsG = svg
      .selectAll("g.resource-row")
      .data(series, (d) => d.project_type)
      .join("g")
      .attr("class", "resource-row")
      .attr("transform", (_, i) => `translate(${MARGIN.left},${MARGIN.top + i * (rowH + ROW_GAP)})`);

    rowsG
      .append("text")
      .attr("class", "row-title")
      .attr("x", 0)
      .attr("y", 12)
      .attr("font-size", 15)
      .attr("font-weight", 600)
      .attr("fill", "var(--text-navy)")
      .text((d) => PROJECT_TYPE_LABELS[d.project_type] || d.project_type);

    rowsG.each(function (d) {
      const g = d3.select(this).append("g").attr("transform", `translate(0,${ROW_LABEL_H})`);

      const allValues = PHASES.flatMap((phase) => d.points.map((p) => p[phase].value)).filter((v) => v != null);
      const maxVal = d3.max(allValues) ?? 0;
      const y = d3
        .scaleLinear()
        .domain([0, maxVal > 0 ? maxVal * 1.15 : 1])
        .range([ROW_PLOT_H, 0])
        .nice();

      g.append("g")
        .call(d3.axisLeft(y).ticks(3).tickSize(-innerW))
        .attr("font-size", 9)
        .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.7))
        .call((axisG) => axisG.select(".domain").remove());

      PHASES.forEach((phase) => {
        // A suppressed month for this phase is skipped from the line (never
        // coerced to 0) — the line simply connects across the gap, and a
        // shared marker glyph below signals the true value was withheld.
        const visible = d.points
          .filter((p) => !p[phase].marker && p[phase].value != null)
          .map((p) => ({ date: new Date(p.month), value: p[phase].value }));

        const line = d3
          .line()
          .x((pt) => x(pt.date))
          .y((pt) => y(pt.value))
          .curve(d3.curveMonotoneX);

        g.append("path")
          .datum(visible)
          .attr("fill", "none")
          .attr("stroke", PHASE_COLORS[phase])
          .attr("stroke-width", 2)
          .attr("d", line);

        g.selectAll(`circle.pt-${phase}`)
          .data(visible)
          .join("circle")
          .attr("class", `pt-${phase}`)
          .attr("cx", (pt) => x(pt.date))
          .attr("cy", (pt) => y(pt.value))
          .attr("r", 2.5)
          .attr("fill", PHASE_COLORS[phase])
          .on("mouseenter", (event, pt) => {
            tooltip.show(
              `<div style="font-weight:600">${monthFormat(pt.date)}</div><div>${PHASE_LABELS[phase]}: ${pt.value.toLocaleString()} people</div>`,
              event
            );
          })
          .on("mousemove", (event) => tooltip.move(event))
          .on("mouseleave", () => tooltip.hide());
      });

      const suppressedMonths = d.points.filter((p) => PHASES.some((phase) => p[phase].marker));
      g.selectAll("text.suppressed-mark")
        .data(suppressedMonths)
        .join("text")
        .attr("class", "suppressed-mark")
        .attr("x", (p) => x(new Date(p.month)))
        .attr("y", ROW_PLOT_H / 2)
        .attr("text-anchor", "middle")
        .attr("font-size", 10)
        .attr("fill", "var(--gray-mid)")
        .text((p) => PHASES.map((phase) => p[phase].marker).find(Boolean))
        .append("title")
        .text("Data suppressed (small cell)");
    });

    svg
      .append("g")
      .attr("transform", `translate(${MARGIN.left},${height - MARGIN.bottom + 6})`)
      .call(d3.axisBottom(x).ticks(Math.min(6, allMonths.length)).tickFormat(d3.utcFormat("%b %Y")))
      .attr("font-size", 10);
  }, [series, width]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
