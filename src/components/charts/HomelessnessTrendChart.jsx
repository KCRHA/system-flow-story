import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";
import ChartLegend from "../ChartLegend.jsx";

const ABOVE_MEDIAN_COLOR = "var(--color-navy)";
const BELOW_MEDIAN_COLOR = "var(--color-light-green)";
const MEDIAN_LINE_COLOR = "var(--chart-5)";
const LINE_COLOR = "var(--gray-dark)";
const SELECTED_RING_COLOR = "var(--color-teal)";

const MARGIN = { top: 20, right: 20, bottom: 40, left: 75 };

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
 * shown, oldest first, for whichever measure is currently selected (see
 * FilterBar's MEASURES — any flow_type the quarterly export carries, not
 * just "experienced homelessness").
 *
 * One dot per quarter, colored by whether that quarter's count fell at/above
 * (dark blue) or below (light green) the median of the quarters actually
 * shown — a reference line marks that same median, so both move together
 * with whatever window/filter is on screen rather than encoding a fixed,
 * system-wide threshold. The quarter matching `selectedQuarter` (the same
 * quarter/month/year currently picked above, collapsed to its containing
 * quarter) gets a ring around its dot; hovering any dot (selected or not)
 * shows its own info panel, which disappears again on mouseleave — no
 * panel is shown until the reader actually hovers something.
 *
 * A suppressed quarter (marker set — see resolveCell/suppression.py) is
 * excluded from the median, the line, and the dots, and marked individually
 * at the axis instead of being silently read as zero.
 *
 * `measureLabel` names the line in the legend ("Active in our system",
 * "Deceased", ...); `unitLabel`/`axisLabel` are the short/long noun phrases
 * for "X ___ ___" in the panel and "___ ___" on the y-axis (see FilterBar's
 * MEASURES). `subject` is who "___" actually means — plain "people" when no
 * demographic filter is active, or e.g. "people who identify as Black" when
 * one is (see OutflowSection's trendSubject/lib/demographics.js) — spliced
 * into both spots in place of a hardcoded "people" so a reader scoped to a
 * demographic category still sees that reflected after scrolling past the
 * filter controls above.
 */
export default function HomelessnessTrendChart({ points, measureLabel, unitLabel, axisLabel, subject = "people", selectedQuarter, width = 960, height = 280 }) {
  const svgRef = useRef(null);

  // Lifted out of the drawing effect below so the legend (in the plain
  // JSX return) can also see whether a real median was computed, not just
  // the SVG — see its "Median during time period shown" item, which
  // should only claim that when a line for it is actually drawn.
  //
  // Suppression only ever hides a NONZERO value below SUPPRESSION_THRESHOLD
  // (11) — a true zero is always shown directly, never suppressed (see
  // resolveCell/suppression.py) — so the full window's sorted values fall
  // into three bands, in this order: any real zeros among the visible
  // quarters (known, smallest), then the suppressed quarters (unknown,
  // each somewhere in [1, 10]), then every other visible quarter sorted
  // normally (known, each >= 11). A zero is NOT simply "below" a
  // suppressed value's rank the way every other visible value is above
  // it — it's below it instead, which is exactly why zeros get their own
  // band rather than being folded into one "visible" sort.
  //
  // The true median of the WHOLE window (not just d3.median of the
  // visible subset, which would silently ignore the suppressed quarters
  // and read too high) is exactly computable as long as every rank it
  // needs lands in the zero or known-positive band. When one instead
  // falls in the middle, unknown band (typically 6+ of a 12-quarter
  // window suppressed), the median itself is just some unknown value
  // under 11 — shown as a message instead of a line, rather than a
  // number that isn't actually knowable.
  const { parsed, visible, suppressed, median, medianKnown } = useMemo(() => {
    const parsed = (points ?? []).map((p) => ({ ...p, date: new Date(p.quarter) }));
    const visible = parsed.filter((p) => !p.marker && p.value != null);
    const suppressed = parsed.filter((p) => p.marker);

    const zeroCount = visible.filter((p) => p.value === 0).length;
    const sortedPositive = visible
      .filter((p) => p.value > 0)
      .map((p) => p.value)
      .sort((a, b) => a - b);
    const suppressedCount = suppressed.length;
    const windowSize = parsed.length;
    const medianRanks = windowSize % 2 === 1 ? [(windowSize + 1) / 2] : [windowSize / 2, windowSize / 2 + 1];
    const valueAtRank = (rank) => {
      if (rank <= zeroCount) return 0;
      if (rank <= zeroCount + suppressedCount) return null;
      return sortedPositive[rank - zeroCount - suppressedCount - 1];
    };
    const medianValues = windowSize > 0 ? medianRanks.map(valueAtRank) : [];
    const medianKnown = medianValues.length > 0 && medianValues.every((v) => v != null);
    const median = medianKnown ? d3.mean(medianValues) : null;

    return { parsed, visible, suppressed, median, medianKnown };
  }, [points]);

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
    const tooltip = createTooltip(container, { variant: "dark" });

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

    g.append("g")
      .call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(",")).tickSize(-innerW))
      .attr("font-size", 10)
      .call((axisG) => axisG.selectAll(".tick line").attr("stroke", "var(--gray-light)").attr("stroke-opacity", 0.5))
      .call((axisG) => axisG.select(".domain").remove());

    // A demographic-scoped subject (see OutflowSection's subjectFor — e.g.
    // "People who identify as American Indian, Alaska Native, or
    // Indigenous active in our system") can run well past the ~220px this
    // rotated label actually has to work with, where it would otherwise
    // get silently clipped by the SVG's own bounds. Truncate with an
    // ellipsis to whatever actually fits, measured against the real
    // rendered text rather than guessed at by character count, and keep
    // the full phrase reachable on hover via the native <title> tooltip.
    const axisLabelFull = `${subject.charAt(0).toUpperCase()}${subject.slice(1)} ${axisLabel}`;
    const axisText = svg
      .append("text")
      .attr("transform", `translate(16,${MARGIN.top + innerH / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 600)
      .attr("fill", "var(--text-navy)")
      .text(axisLabelFull);
    let truncated = axisLabelFull;
    while (axisText.node().getComputedTextLength() > innerH && truncated.length > 1) {
      truncated = truncated.slice(0, -1);
      axisText.text(`${truncated}…`);
    }
    axisText.append("title").text(axisLabelFull);

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
        .text(`Median during time period shown: ${Math.round(median).toLocaleString()}`);
    } else if (suppressed.length > 0) {
      // Too many of this window's quarters are suppressed to know where
      // the true median actually falls — no line to draw, just a note
      // explaining why one isn't shown here.
      g.append("text")
        .attr("x", innerW)
        .attr("y", 10)
        .attr("text-anchor", "end")
        .attr("font-size", 10)
        .attr("fill", "var(--text-gray)")
        .text("Median is below the suppression threshold (fewer than 11)");
    }

    // `.defined()` on the full `parsed` series (not just `visible`) so d3
    // breaks the line at every suppressed/missing quarter instead of
    // bridging straight over it — connecting across a suppressed gap would
    // visually read as a real, known value in between, when the true count
    // there could be anywhere under the suppression threshold (see
    // resolveCell/suppression.py). A suppressed quarter with real data on
    // both sides of it renders as two separate segments with a visible
    // break between them; one with no visible neighbor on either side (a
    // single isolated point) renders as a lone dot instead.
    const line = d3
      .line()
      .defined((p) => !p.marker && p.value != null)
      .x((p) => x(p.date))
      .y((p) => y(p.value))
      .curve(d3.curveMonotoneX);

    g.append("path").datum(parsed).attr("fill", "none").attr("stroke", LINE_COLOR).attr("stroke-width", 2).attr("d", line);

    // One panel shared between hover and the default "selected period"
    // state — same content shape either way, just a different point and an
    // "(selected)" suffix when it's the one matching selectedQuarter.
    function panelHtml(p, index) {
      const isSelected = p.quarter === selectedQuarter;
      const label = quarterLabel(p.date) + (isSelected ? " (selected)" : "");
      const lines = [`<div style="font-weight:700">${label}</div>`, `<div>${p.value.toLocaleString()} ${subject} ${unitLabel}</div>`];
      if (median != null) {
        const delta = Math.round(p.value - median);
        lines.push(delta === 0 ? `<div>At the median</div>` : `<div>${Math.abs(delta).toLocaleString()} ${delta > 0 ? "above" : "below"} the median</div>`);
      }
      const prev = visible[index - 1];
      if (prev) {
        if (p.value === prev.value) {
          lines.push(`<div>No change vs. ${quarterLabel(prev.date)}</div>`);
        } else if (!prev.value) {
          lines.push(`<div>New vs. ${quarterLabel(prev.date)}</div>`);
        } else {
          const percent = Math.round((Math.abs(p.value - prev.value) / prev.value) * 100);
          lines.push(`<div>${p.value > prev.value ? "▲" : "▼"} ${percent}% vs. ${quarterLabel(prev.date)}</div>`);
        }
      }
      return lines.join("");
    }

    const selectedPoint = visible.find((p) => p.quarter === selectedQuarter) ?? null;

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
        tooltip.show(panelHtml(p, visible.indexOf(p)), event);
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    // Ring marking whichever point matches the dashboard's current period
    // selection — drawn after the plain dots so it sits on top of (around)
    // the matching one rather than under it. Purely visual; hovering it
    // shows the same panel as any other point (via the "pt" circles above,
    // which this sits directly on top of).
    if (selectedPoint) {
      g.append("circle")
        .attr("class", "pt-selected-ring")
        .attr("cx", x(selectedPoint.date))
        .attr("cy", y(selectedPoint.value))
        .attr("r", 9)
        .attr("fill", "none")
        .attr("stroke", SELECTED_RING_COLOR)
        .attr("stroke-width", 2)
        .attr("pointer-events", "none");
    }

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
  }, [points, parsed, visible, suppressed, median, medianKnown, measureLabel, unitLabel, axisLabel, subject, selectedQuarter, width, height]);

  return (
    <div>
      <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />
      <ChartLegend
        items={[
          { kind: "line", color: LINE_COLOR, label: measureLabel },
          { kind: "dot", color: ABOVE_MEDIAN_COLOR, label: "At or above the median" },
          { kind: "dot", color: BELOW_MEDIAN_COLOR, label: "Below the median" },
          // Omitted (rather than left pointing at a line that isn't drawn)
          // whenever too many quarters are suppressed to know the true
          // median — see the matching "below the suppression threshold"
          // message in place of the line itself, above. "during time
          // period shown" names the window, not the set of visible dots —
          // this accounts for suppressed quarters' rank too, so it can
          // land above what a plain median of only the visible dots would.
          ...(medianKnown ? [{ kind: "dashed", color: MEDIAN_LINE_COLOR, label: "Median during time period shown" }] : []),
          { kind: "ring", color: SELECTED_RING_COLOR, label: "Selected period" },
        ]}
      />
    </div>
  );
}
