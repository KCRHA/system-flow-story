import { useEffect, useRef } from "react";
import * as d3 from "d3";

const PROJECT_TYPE_LABELS = { ph: "Permanent Housing", th: "Transitional Housing", es: "Emergency Shelter", rrh: "Rapid Re-Housing" };

/** rows: [{ project_type, units_in_system }] — one bar per project type. */
export default function CapacityUnitsChart({ rows, width = 640, height = 220 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!rows?.length) {
      // Clear the previous drawing: otherwise a selection with no rows (e.g. a
      // dimension this file doesn't carry) leaves the last chart on screen.
      d3.select(svgRef.current).selectAll("*").remove();
      return;
    }
    const margin = { top: 10, right: 60, bottom: 10, left: 160 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const y = d3.scaleBand().domain(rows.map((d) => d.project_type)).range([0, innerH]).padding(0.3);
    const x = d3.scaleLinear().domain([0, d3.max(rows, (d) => d.units_in_system) * 1.15]).range([0, innerW]);

    g.selectAll("rect.bar")
      .data(rows, (d) => d.project_type)
      .join("rect")
      .attr("class", "bar")
      .attr("y", (d) => y(d.project_type))
      .attr("height", y.bandwidth())
      .attr("x", 0)
      .attr("fill", "var(--chart-2)")
      .transition()
      .duration(400)
      .attr("width", (d) => x(d.units_in_system));

    g.selectAll("text.label")
      .data(rows, (d) => d.project_type)
      .join("text")
      .attr("class", "label")
      .attr("x", -10)
      .attr("y", (d) => y(d.project_type) + y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .attr("text-anchor", "end")
      .attr("font-size", 13)
      .attr("fill", "var(--text-dark)")
      .text((d) => PROJECT_TYPE_LABELS[d.project_type] || d.project_type);

    g.selectAll("text.value")
      .data(rows, (d) => d.project_type)
      .join("text")
      .attr("class", "value")
      .attr("y", (d) => y(d.project_type) + y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .attr("font-size", 13)
      .attr("fill", "var(--text-dark)")
      .text((d) => d.units_in_system.toLocaleString())
      .transition()
      .duration(400)
      .attr("x", (d) => x(d.units_in_system) + 8);
  }, [rows, width, height]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
