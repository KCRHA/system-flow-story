import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";

const MARGIN = { top: 10, right: 10, bottom: 20, left: 46 };

/**
 * points: [{ year, month, units_in_system, pct_utilization }], oldest to
 * newest, one snapshot per year (that year's last available month) ending at
 * the selected year — so the final point always matches the card's own
 * "units as of {month}" headline figure above this chart.
 *
 * Renders a small-multiple area+line: the "Capacity" line is units_in_system,
 * the "In use" area is units_in_system * pct_utilization (the implied
 * occupied-unit count), and a hollow ring marks the selected (final) year —
 * same three legend entries as CapacitySection's own ChartLegend above the
 * card row.
 */
export default function CapacityCardChart({ points, width = 300, height = 150 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    const container = svgRef.current.parentElement;
    svg.selectAll("*").remove();
    clearTooltip(container);
    if (!points?.length) return;

    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    const g = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    const tooltip = createTooltip(container);

    const data = points.map((d) => ({
      ...d,
      inUse: d.units_in_system != null && d.pct_utilization != null ? d.units_in_system * d.pct_utilization : null,
    }));

    const x = d3.scalePoint().domain(data.map((d) => d.year)).range([0, innerW]).padding(0.5);
    const y = d3
      .scaleLinear()
      .domain([0, (d3.max(data, (d) => d.units_in_system) ?? 0) * 1.1])
      .range([innerH, 0])
      .nice();

    g.append("g")
      .call(d3.axisLeft(y).ticks(3).tickFormat(d3.format(",")).tickSize(-innerW))
      .attr("font-size", 9)
      .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.7))
      .call((axisG) => axisG.select(".domain").remove());

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickSize(0))
      .attr("font-size", 10)
      .call((axisG) => axisG.select(".domain").attr("stroke", "var(--gray-light)"));

    const area = d3
      .area()
      .defined((d) => d.inUse != null)
      .x((d) => x(d.year))
      .y0(innerH)
      .y1((d) => y(d.inUse))
      .curve(d3.curveMonotoneX);

    const line = d3
      .line()
      .defined((d) => d.units_in_system != null)
      .x((d) => x(d.year))
      .y((d) => y(d.units_in_system))
      .curve(d3.curveMonotoneX);

    g.append("path").datum(data).attr("fill", "var(--chart-7)").attr("fill-opacity", 0.35).attr("d", area);
    g.append("path").datum(data).attr("fill", "none").attr("stroke", "var(--text-navy)").attr("stroke-width", 2).attr("d", line);

    g.selectAll("circle.hover-pt")
      .data(data.filter((d) => d.units_in_system != null))
      .join("circle")
      .attr("class", "hover-pt")
      .attr("cx", (d) => x(d.year))
      .attr("cy", (d) => y(d.units_in_system))
      .attr("r", 9)
      .attr("fill", "transparent")
      .on("mouseenter", (event, d) => {
        tooltip.show(
          `<div style="font-weight:600">${d.year}</div>` +
            `<div>${d.units_in_system.toLocaleString()} units</div>` +
            (d.pct_utilization != null ? `<div>${Math.round(d.pct_utilization * 100)}% in use</div>` : ""),
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    // Selected-year marker — a hollow ring at the top of the "in use" area's
    // last point (not the capacity line above it), matching the approved
    // mockup and the "Selected year" legend swatch.
    const last = data.at(-1);
    if (last?.inUse != null) {
      g.append("circle")
        .attr("cx", x(last.year))
        .attr("cy", y(last.inUse))
        .attr("r", 5)
        .attr("fill", "#fff")
        .attr("stroke", "var(--text-navy)")
        .attr("stroke-width", 2)
        .attr("pointer-events", "none");
    }
  }, [points, width, height]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
