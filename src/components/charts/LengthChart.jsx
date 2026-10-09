import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";
import { INSUFFICIENT_POPULATION_MARKER } from "../../lib/loadData.js";

const monthFormat = d3.utcFormat("%b %Y");

/** Median line with a p25–p75 band, over months. `compact` shrinks margins/
 * tick count/font for small-multiple use (see LengthByExitGrid) — the only
 * sizing LengthSection itself still uses directly. `yMax`, when given,
 * fixes the y-domain's upper bound instead of each chart computing its own
 * from `rows` — LengthByExitGrid passes the same value to every panel in a
 * row so they share one scale and read as directly comparable, per the
 * approved mockup. `yAxisLabel`, when given, draws a single rotated axis
 * label in the chart's own left margin — LengthByExitGrid only passes this
 * to the first panel in a row, since repeating it on every panel would be
 * redundant once they're all on the same scale. `isExit` (default true)
 * picks the tooltip's tense: a real exit (Permanently Housed, Inactive,
 * Aged Out) has a duration that's over and done, so it reads "experienced
 * homelessness for"; Still Active hasn't ended yet, so it stays in the
 * present ("were experiencing homelessness between") — see
 * LengthByExitGrid, which passes `isExit={key !== "still_active"}`. */
export default function LengthChart({ rows, width = 720, height = 380, compact = false, yMax = null, yAxisLabel = null, isExit = true }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!rows?.length) return;
    const margin = compact ? { top: 12, right: 12, bottom: 22, left: 44 } : { top: 20, right: 20, bottom: 30, left: 56 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    const tickFontSize = compact ? 9 : 11;
    const yTicks = compact ? 2 : 3;

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
    const localMax = d3.max(parsed, (d) => d.p75_days ?? d.median_days) ?? 0;
    const y = d3
      .scaleLinear()
      .domain([0, yMax ?? (localMax > 0 ? localMax * 1.1 : 1)])
      .range([innerH, 0])
      .nice();

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    // One tick per calendar year (e.g. "Jan 2024", "Jan 2025") rather than
    // an arbitrary evenly-spaced count — matches the approved mockup's
    // sparser x-axis and reads more naturally for a ~2-year trailing window
    // than mid-year tick labels would.
    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(d3.utcYear.every(1)).tickFormat(d3.utcFormat("%b %Y")))
      .attr("font-size", tickFontSize);

    // Full-width gridlines (not just tick marks) at each y-tick, matching
    // HomelessnessTrendChart's own axis convention — the domain line itself
    // is removed since the gridlines already mark the baseline.
    g.append("g")
      .call(d3.axisLeft(y).ticks(yTicks).tickSize(-innerW))
      .attr("font-size", tickFontSize)
      .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.7))
      .call((axisG) => axisG.select(".domain").remove());

    if (yAxisLabel) {
      svg
        .append("text")
        .attr("transform", `translate(12,${margin.top + innerH / 2}) rotate(-90)`)
        .attr("text-anchor", "middle")
        .attr("font-size", tickFontSize)
        .attr("font-weight", 600)
        .attr("fill", "var(--text-navy)")
        .text(yAxisLabel);
    }

    // `.defined()` on the full `parsed` series (not a pre-filtered
    // suppressed-free subset) so the median line below breaks at a
    // suppressed month instead of silently bridging straight over it —
    // connecting across a suppressed gap would draw a smooth, confident line
    // through months whose real value is unknown (see
    // HomelessnessTrendChart's own line generator for the same convention).
    const defined = (d) => !d.suppression_marker;

    const suppressed = parsed.filter((d) => d.suppression_marker);
    const visible = parsed.filter((d) => !d.suppression_marker);

    // curveMonotoneX, matching HomelessnessTrendChart's own run chart — same
    // smoothing on the band, its boundary lines, and the median line below,
    // rather than the band curving while the line stayed jagged.
    const band = d3
      .area()
      .curve(d3.curveMonotoneX)
      .x((d) => x(d.date))
      .y0((d) => y(d.p25_days ?? d.median_days))
      .y1((d) => y(d.p75_days ?? d.median_days));
    const bandEdge = (accessor) =>
      d3.line().curve(d3.curveMonotoneX).x((d) => x(d.date)).y((d) => y(accessor(d) ?? d.median_days));

    // The band (fill + its own p25/p75 boundary lines) gets a soft visual
    // buffer the median line doesn't: each run of consecutive visible months
    // extends half a month past its last real point into an adjoining
    // suppressed gap, flat at that real point's own value — a cushion
    // against the gap reading as a hard, sudden cliff — rather than hard-
    // stopping exactly at the last known month the way the line (a much
    // more precise-looking claim) still does. A gap of 2+ suppressed months
    // still reads as a true gap in the middle; only its two edges, nearest
    // the real data on either side, get this half-month extension.
    const midpointDate = (a, b) => new Date((a.getTime() + b.getTime()) / 2);
    let runStart = null;
    for (let i = 0; i <= parsed.length; i++) {
      const isVisible = i < parsed.length && !parsed[i].suppression_marker;
      if (isVisible && runStart == null) runStart = i;
      if (!isVisible && runStart != null) {
        const runEnd = i - 1;
        const run = parsed.slice(runStart, runEnd + 1);
        const first = run[0];
        const last = run[run.length - 1];
        const bandPoints = [...run];
        if (runStart > 0) {
          bandPoints.unshift({ ...first, date: midpointDate(parsed[runStart - 1].date, first.date) });
        }
        if (runEnd < parsed.length - 1) {
          bandPoints.push({ ...last, date: midpointDate(last.date, parsed[runEnd + 1].date) });
        }
        g.append("path").datum(bandPoints).attr("fill", "var(--chart-7)").attr("opacity", 0.35).attr("d", band);
        g.append("path")
          .datum(bandPoints)
          .attr("fill", "none")
          .attr("stroke", "var(--chart-7)")
          .attr("stroke-width", 1)
          .attr("d", bandEdge((d) => d.p25_days));
        g.append("path")
          .datum(bandPoints)
          .attr("fill", "none")
          .attr("stroke", "var(--chart-7)")
          .attr("stroke-width", 1)
          .attr("d", bandEdge((d) => d.p75_days));
        runStart = null;
      }
    }

    const line = d3
      .line()
      .defined(defined)
      .curve(d3.curveMonotoneX)
      .x((d) => x(d.date))
      .y((d) => y(d.median_days));

    g.append("path")
      .datum(parsed)
      .attr("fill", "none")
      .attr("stroke", "var(--chart-2)")
      .attr("stroke-width", compact ? 2 : 2.5)
      .attr("d", line);

    g.selectAll("text.suppressed-mark")
      .data(suppressed)
      .join("text")
      .attr("class", "suppressed-mark")
      .attr("x", (d) => x(d.date))
      // Not innerH/2 (plain vertical centering, tied to nothing about the
      // data) — y(10) instead, since a suppressed cell here means the
      // underlying population was below 11, i.e. close to zero. Anchoring
      // the mark there reads as "small value," where mid-chart could be
      // mistaken for a real plotted point in that range.
      .attr("y", y(10))
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
            `<div>50% of people ${isExit ? "experienced homelessness for" : "were experiencing homelessness between"} ${Math.round(d.p25_days).toLocaleString()}–${Math.round(d.p75_days).toLocaleString()} days</div>`,
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());
  }, [rows, width, height, compact, yMax, yAxisLabel, isExit]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
