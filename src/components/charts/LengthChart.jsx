import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";
import { INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";

const monthFormat = d3.utcFormat("%b %Y");

/** Median line with a p25–p75 band, over months. */
export default function LengthChart({ rows, width = 720, height = 380 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!rows?.length) {
      // Clear the previous drawing: otherwise a selection with no rows (e.g. a
      // dimension this file doesn't carry) leaves the last chart on screen.
      d3.select(svgRef.current).selectAll("*").remove();
      return;
    }
    const margin = { top: 20, right: 20, bottom: 30, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const parsed = rows
      .map((r) => ({ ...r, date: new Date(r.month) }))
      .sort((a, b) => a.date - b.date);

    // scaleUtc/utcFormat, not scaleTime/timeFormat: "YYYY-MM-DD" parses as
    // UTC midnight, but timeFormat renders in the browser's local
    // timezone — for anyone west of UTC (all of the US) that silently
    // shifts every month label back by one (e.g. "2024-03-01" -> "Feb
    // 2024" in Pacific time). Treating dates as UTC throughout sidesteps
    // the conversion entirely.
    const x = d3.scaleUtc().domain(d3.extent(parsed, (d) => d.date)).range([0, innerW]);
    const y = d3
      .scaleLinear()
      .domain([0, d3.max(parsed, (d) => d.p75_days ?? d.median_days) * 1.1])
      .range([innerH, 0]);

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(6).tickFormat(d3.utcFormat("%b %Y")))
      .attr("font-size", 11);

    g.append("g").call(d3.axisLeft(y).ticks(5)).attr("font-size", 11);

    const band = d3
      .area()
      .x((d) => x(d.date))
      .y0((d) => y(d.p25_days ?? d.median_days))
      .y1((d) => y(d.p75_days ?? d.median_days));

    const suppressed = parsed.filter((d) => d.suppression_marker);
    const visible = parsed.filter((d) => !d.suppression_marker);

    g.append("path").datum(visible).attr("fill", "var(--chart-7)").attr("opacity", 0.35).attr("d", band);

    const line = d3
      .line()
      .x((d) => x(d.date))
      .y((d) => y(d.median_days));

    g.append("path")
      .datum(visible)
      .attr("fill", "none")
      .attr("stroke", "var(--chart-2)")
      .attr("stroke-width", 2.5)
      .attr("d", line);

    g.selectAll("text.suppressed-mark")
      .data(suppressed)
      .join("text")
      .attr("class", "suppressed-mark")
      .attr("x", (d) => x(d.date))
      .attr("y", innerH / 2)
      .attr("text-anchor", "middle")
      .attr("font-size", (d) => (d.suppression_marker === INSUFFICIENT_POPULATION_MARKER ? 10 : 13))
      .attr("fill", "var(--gray-mid)")
      .text((d) => (d.suppression_marker === INSUFFICIENT_POPULATION_MARKER ? "too small" : d.suppression_marker))
      .on("mouseenter", (event, d) => {
        const message =
          d.suppression_marker === INSUFFICIENT_POPULATION_MARKER
            ? "Population too small to safely display for this combination"
            : "Data suppressed (small cell)";
        tooltip.show(`<div style="font-weight:600">${monthFormat(d.date)}</div><div>${message}</div>`, event);
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    g.selectAll("circle.median-point")
      .data(visible)
      .join("circle")
      .attr("class", "median-point")
      .attr("cx", (d) => x(d.date))
      .attr("cy", (d) => y(d.median_days))
      .attr("r", 3)
      .attr("fill", "var(--chart-2)")
      .on("mouseenter", (event, d) => {
        tooltip.show(
          `<div style="font-weight:600">${monthFormat(d.date)}</div>` +
            `<div>Median: ${Math.round(d.median_days).toLocaleString()} days</div>` +
            `<div>50% of people were experiencing homelessness between ${Math.round(d.p25_days).toLocaleString()}–${Math.round(d.p75_days).toLocaleString()} days</div>`,
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());
  }, [rows, width, height]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
