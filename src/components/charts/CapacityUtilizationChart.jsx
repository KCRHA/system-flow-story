import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";

const PROJECT_TYPE_LABELS = { ph: "Permanent Housing", th: "Transitional Housing", es: "Emergency Shelter", rrh: "Rapid Re-Housing" };

const MARGIN = { top: 8, right: 20, bottom: 26, left: 54 };
const ROW_LABEL_H = 22;
const ROW_PLOT_H = 70;
const ROW_GAP = 32;

function quarterLabel(date) {
  const q = Math.floor(date.getUTCMonth() / 3) + 1;
  return `Q${q} ${date.getUTCFullYear()}`;
}

/**
 * series: [{ project_type, points: [{ quarter, pct_utilization }] }]
 *
 * One small-multiple row per project type, a trailing 3-year (12-quarter)
 * window on the x-axis. Unlike Resource Access's per-row auto-fit, every
 * row here shares one 0-100% y-axis — utilization is already a bounded
 * percentage for every project type, so a shared scale is what makes
 * cross-type comparison (e.g. PH holding near 95% while RRH dips lower)
 * visible; auto-fitting each row would erase that.
 */
export default function CapacityUtilizationChart({ series, width = 720 }) {
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

    const allQuarters = (series[0]?.points ?? []).map((p) => new Date(p.quarter));
    // scaleUtc, not scaleTime: "YYYY-MM-DD" parses as UTC midnight, and a
    // local-timezone-based scale/format (west of UTC, i.e. all of the US)
    // would silently shift every label back — right at a quarter
    // boundary, back a whole quarter.
    const x = d3.scaleUtc().domain(d3.extent(allQuarters)).range([0, innerW]);
    const y = d3.scaleLinear().domain([0, 1]).range([ROW_PLOT_H, 0]);

    const rowsG = svg
      .selectAll("g.util-row")
      .data(series, (d) => d.project_type)
      .join("g")
      .attr("class", "util-row")
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

      g.append("g")
        .call(d3.axisLeft(y).ticks(3).tickFormat(d3.format(".0%")).tickSize(-innerW))
        .attr("font-size", 9)
        .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.7))
        .call((axisG) => axisG.select(".domain").remove());

      const visible = d.points
        .filter((p) => p.pct_utilization != null)
        .map((p) => ({ date: new Date(p.quarter), value: p.pct_utilization }));

      const line = d3
        .line()
        .x((pt) => x(pt.date))
        .y((pt) => y(pt.value))
        .curve(d3.curveMonotoneX);

      g.append("path").datum(visible).attr("fill", "none").attr("stroke", "var(--chart-2)").attr("stroke-width", 2).attr("d", line);

      g.selectAll("circle.pt")
        .data(visible)
        .join("circle")
        .attr("class", "pt")
        .attr("cx", (pt) => x(pt.date))
        .attr("cy", (pt) => y(pt.value))
        .attr("r", 2.5)
        .attr("fill", "var(--chart-2)")
        .on("mouseenter", (event, pt) => {
          tooltip.show(
            `<div style="font-weight:600">${PROJECT_TYPE_LABELS[d.project_type] || d.project_type}, ${quarterLabel(pt.date)}</div>` +
              `<div>${(pt.value * 100).toFixed(0)}% utilization</div>`,
            event
          );
        })
        .on("mousemove", (event) => tooltip.move(event))
        .on("mouseleave", () => tooltip.hide());
    });

    svg
      .append("g")
      .attr("transform", `translate(${MARGIN.left},${height - MARGIN.bottom + 6})`)
      .call(d3.axisBottom(x).ticks(Math.min(12, allQuarters.length)).tickFormat(quarterLabel))
      .attr("font-size", 10);
  }, [series, width]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
