import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";
import { INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";

const RETURNED_COLOR = "var(--chart-3)";
const REMAINED_HOUSED_COLOR = "var(--chart-2)";
// Below this segment height, a centered label wouldn't fit inside the
// segment (and white text would clip past its edges) — float it just
// outside the segment, in the segment's own color, instead.
const MIN_LABEL_SEGMENT_H = 16;

function quarterLabel(dateStr) {
  // utcFormat/UTC month, not local: "YYYY-MM-DD" parses as UTC midnight,
  // and a local-timezone read (west of UTC, i.e. all of the US) can shift
  // it back a day and, right at a quarter boundary, a whole quarter.
  const d = new Date(dateStr);
  const q = Math.floor(d.getUTCMonth() / 3) + 1;
  return `Q${q} ${d.getUTCFullYear()}`;
}

/**
 * One stacked bar per exit-quarter cohort: total height is n_exited (how
 * many people exited to permanent housing that quarter), split into a
 * "returned" segment (n_returned, within the 6-month window) and a
 * "remained housed" segment, each labeled with its share of the total —
 * so the exit volume, the split, and the exact rate all read at a glance.
 * Callers are expected to have already scoped `rows` to window_complete
 * cohorts only (see LengthSection.jsx) — a cohort whose 6-month window
 * hasn't fully elapsed doesn't have a reportable rate at all.
 */
export default function ReturnCohortChart({ rows, width = 720, height = 340 }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!rows?.length) return;
    const margin = { top: 20, right: 20, bottom: 50, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const parsed = [...rows].sort((a, b) => new Date(a.exit_quarter) - new Date(b.exit_quarter));

    const x = d3
      .scaleBand()
      .domain(parsed.map((d) => d.exit_quarter))
      .range([0, innerW])
      .padding(0.25);
    const maxExited = d3.max(parsed, (d) => (d.suppression_marker ? 0 : d.n_exited)) ?? 0;
    const y = d3
      .scaleLinear()
      .domain([0, maxExited > 0 ? maxExited * 1.1 : 1])
      .range([innerH, 0])
      .nice();

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickFormat(quarterLabel))
      .selectAll("text")
      .attr("transform", "rotate(-40)")
      .style("text-anchor", "end")
      .attr("font-size", 10);

    g.append("g").call(d3.axisLeft(y).ticks(5)).attr("font-size", 11);

    const bars = g
      .selectAll("g.cohort-bar")
      .data(parsed)
      .join("g")
      .attr("class", "cohort-bar")
      .attr("transform", (d) => `translate(${x(d.exit_quarter)},0)`);

    // "Remained housed" segment: from the top of "returned" up to n_exited.
    bars
      .append("rect")
      .attr("width", x.bandwidth())
      .attr("y", (d) => (d.suppression_marker ? innerH : y(d.n_exited)))
      .attr("height", (d) => (d.suppression_marker ? 0 : y(d.n_returned) - y(d.n_exited)))
      .attr("fill", REMAINED_HOUSED_COLOR);

    // "Returned" segment: from the axis up to n_returned.
    bars
      .append("rect")
      .attr("width", x.bandwidth())
      .attr("y", (d) => (d.suppression_marker ? innerH : y(d.n_returned)))
      .attr("height", (d) => (d.suppression_marker ? 0 : innerH - y(d.n_returned)))
      .attr("fill", RETURNED_COLOR);

    bars
      .on("mouseenter", (event, d) => {
        const suppressedMessage =
          d.suppression_marker === INSUFFICIENT_POPULATION_MARKER
            ? "Population too small to safely display for this combination"
            : "Data suppressed (small cell)";
        tooltip.show(
          d.suppression_marker
            ? `<div style="font-weight:600">${quarterLabel(d.exit_quarter)}</div><div>${suppressedMessage}</div>`
            : `<div style="font-weight:600">${quarterLabel(d.exit_quarter)}</div>` +
                `<div>${d.n_exited.toLocaleString()} exited, ${d.n_returned.toLocaleString()} returned (${Math.round(d.pct_returned * 100)}%)</div>`,
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    // Percent labels for each segment — centered inside it when there's
    // room, floated just outside (in the segment's own color) otherwise.
    const labeled = parsed.filter((d) => !d.suppression_marker && d.pct_returned != null);
    const bandCenter = x.bandwidth() / 2;

    const returnedLabels = g
      .selectAll("text.pct-returned")
      .data(labeled)
      .join("text")
      .attr("class", "pct-returned")
      .attr("x", (d) => x(d.exit_quarter) + bandCenter)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 600)
      .text((d) => `${(d.pct_returned * 100).toFixed(0)}%`);

    returnedLabels.each(function (d) {
      const segTop = y(d.n_returned);
      const segH = innerH - segTop;
      const fits = segH >= MIN_LABEL_SEGMENT_H;
      d3.select(this)
        .attr("y", fits ? (segTop + innerH) / 2 : segTop - 5)
        .attr("dy", fits ? "0.35em" : null)
        .attr("fill", fits ? "#fff" : RETURNED_COLOR);
    });

    const remainedLabels = g
      .selectAll("text.pct-remained")
      .data(labeled)
      .join("text")
      .attr("class", "pct-remained")
      .attr("x", (d) => x(d.exit_quarter) + bandCenter)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 600)
      .text((d) => `${((1 - d.pct_returned) * 100).toFixed(0)}%`);

    remainedLabels.each(function (d) {
      const segTop = y(d.n_exited);
      const segBottom = y(d.n_returned);
      const segH = segBottom - segTop;
      const fits = segH >= MIN_LABEL_SEGMENT_H;
      d3.select(this)
        .attr("y", fits ? (segTop + segBottom) / 2 : segTop - 5)
        .attr("dy", fits ? "0.35em" : null)
        .attr("fill", fits ? "#fff" : REMAINED_HOUSED_COLOR);
    });

    // A suppressed cohort has no bar to show — mark it explicitly at the
    // axis rather than leaving a blank gap that reads as "0 exited".
    g.selectAll("text.suppression-mark")
      .data(parsed.filter((d) => d.suppression_marker))
      .join("text")
      .attr("class", "suppression-mark")
      .attr("x", (d) => x(d.exit_quarter) + bandCenter)
      .attr("y", innerH - 8)
      .attr("text-anchor", "middle")
      .attr("font-size", (d) => (d.suppression_marker === INSUFFICIENT_POPULATION_MARKER ? 10 : 13))
      .attr("fill", "var(--gray-mid)")
      .text((d) => (d.suppression_marker === INSUFFICIENT_POPULATION_MARKER ? "too small" : d.suppression_marker));
  }, [rows, width, height]);

  return (
    <div>
      <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />
      <p className="suppressed-note">
        Bar height is the number of people who exited to permanent housing that quarter, split into the{" "}
        <span style={{ color: REMAINED_HOUSED_COLOR }}>share who remained housed</span> and the{" "}
        <span style={{ color: RETURNED_COLOR }}>share who returned to homelessness</span> within 6 months.
      </p>
    </div>
  );
}
