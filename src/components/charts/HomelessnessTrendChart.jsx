import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";
import ChartLegend from "../ChartLegend.jsx";

const ABOVE_MEDIAN_COLOR = "var(--color-navy)";
const BELOW_MEDIAN_COLOR = "var(--color-light-green)";
const MEDIAN_LINE_COLOR = "var(--gray-light)";
const LINE_COLOR = "var(--gray-dark)";

const MARGIN = { top: 20, right: 20, bottom: 40, left: 60 };

// Same UTC-safe parsing/format as every other quarterly chart here —
// "YYYY-MM-DD" parses as UTC midnight, and a local-timezone read (west of
// UTC, i.e. all of the US) can shift it back a day and, right at a quarter
// boundary, a whole quarter.
function quarterLabel(date) {
  const q = Math.floor(date.getUTCMonth() / 3) + 1;
  return `Q${q} ${date.getUTCFullYear()}`;
}

/**
 * points: [{ quarter: "YYYY-MM-DD", value: number|null, marker: string|null }],
 * already the trailing (up to 3-year, 12-quarter) window the caller wants
 * shown, oldest first.
 *
 * One dot per quarter, colored by whether that quarter's count fell at/above
 * (dark blue) or below (light green) the median of the quarters actually
 * shown — a reference line marks that same median, so both move together
 * with whatever window/filter is on screen rather than encoding a fixed,
 * system-wide threshold.
 *
 * A suppressed quarter (marker set — see resolveCell/suppression.py) is
 * excluded from the median, the line, and the dots, and marked individually
 * at the axis instead of being silently read as zero.
 */
export default function HomelessnessTrendChart({ points, width = 960, height = 280 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!points?.length) return;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    const parsed = points.map((p) => ({ ...p, date: new Date(p.quarter) }));
    const visible = parsed.filter((p) => !p.marker && p.value != null);
    const suppressed = parsed.filter((p) => p.marker);

    const x = d3
      .scaleUtc()
      .domain(d3.extent(parsed, (p) => p.date))
      .range([0, innerW]);
    const maxValue = d3.max(visible, (p) => p.value) ?? 0;
    const y = d3
      .scaleLinear()
      .domain([0, maxValue > 0 ? maxValue * 1.1 : 1])
      .range([innerH, 0])
      .nice();
    const median = visible.length ? d3.median(visible, (p) => p.value) : null;

    g.append("g")
      .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(",")).tickSize(-innerW))
      .attr("font-size", 10)
      .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.5))
      .call((axisG) => axisG.select(".domain").remove());

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(
        d3
          .axisBottom(x)
          .tickValues(parsed.map((p) => p.date))
          .tickFormat(quarterLabel)
      )
      .selectAll("text")
      .attr("transform", "rotate(-40)")
      .style("text-anchor", "end")
      .attr("font-size", 10);

    // Responsive reference line at the median of the quarters shown — not a
    // fixed threshold, so it tracks whatever window/filter is active.
    if (median != null) {
      g.append("line")
        .attr("x1", 0)
        .attr("x2", innerW)
        .attr("y1", y(median))
        .attr("y2", y(median))
        .attr("stroke", MEDIAN_LINE_COLOR)
        .attr("stroke-width", 1.5)
        .attr("stroke-dasharray", "4,3");

      g.append("text")
        .attr("x", innerW)
        .attr("y", y(median) - 6)
        .attr("text-anchor", "end")
        .attr("font-size", 10)
        .attr("fill", "var(--text-gray)")
        .text(`Median: ${Math.round(median).toLocaleString()}`);
    }

    const line = d3
      .line()
      .x((p) => x(p.date))
      .y((p) => y(p.value))
      .curve(d3.curveMonotoneX);

    g.append("path").datum(visible).attr("fill", "none").attr("stroke", LINE_COLOR).attr("stroke-width", 2).attr("d", line);

    g.selectAll("circle.pt")
      .data(visible)
      .join("circle")
      .attr("class", "pt")
      .attr("cx", (p) => x(p.date))
      .attr("cy", (p) => y(p.value))
      .attr("r", 5)
      .attr("fill", (p) => (p.value >= median ? ABOVE_MEDIAN_COLOR : BELOW_MEDIAN_COLOR))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5)
      .on("mouseenter", (event, p) => {
        tooltip.show(
          `<div style="font-weight:600">${quarterLabel(p.date)}</div><div>${p.value.toLocaleString()} people</div>`,
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    // Suppressed quarters get no dot or line segment — mark them at the
    // axis instead of leaving a silent gap that could read as "0 people"
    // (a suppressed cell is never a real zero — see resolveCell).
    g.selectAll("text.suppression-mark")
      .data(suppressed)
      .join("text")
      .attr("class", "suppression-mark")
      .attr("x", (p) => x(p.date))
      .attr("y", innerH - 8)
      .attr("text-anchor", "middle")
      .attr("font-size", 10)
      .attr("fill", "var(--gray-mid)")
      .text("too small");
  }, [points, width, height]);

  return (
    <div>
      <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />
      <ChartLegend
        items={[
          { color: ABOVE_MEDIAN_COLOR, label: "At or above the median" },
          { color: BELOW_MEDIAN_COLOR, label: "Below the median" },
        ]}
      />
    </div>
  );
}
