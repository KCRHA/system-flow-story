import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { FLOW_COLORS } from "../../lib/flowColors.js";

export const ACTIVE_COLOR = "var(--chart-2)";
export const ACTIVE_LABEL = "Active";
const FIELD_GRAY = "var(--gray-light)";

const FIELD_DOT_R = 2.2;
const FIELD_RING_GAP = FIELD_DOT_R * 2.4;
const CENTER_DOT_R = 3;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const CLUSTER_DENSITY_K = 8; // px of cluster radius per sqrt(dot) — bigger groups get visibly bigger clusters
// px of center-circle radius per sqrt(dot) — calibrated so the "All
// Population" segment's typical dot count (~459) lands at roughly the
// same radius the old fixed 0.2*min(w,h) constant gave it, so that
// common case looks the same as before, while a much smaller population
// (e.g. Veterans) now gets a smaller, denser-looking circle instead of
// the same fixed footprint stretched thin.
const CENTER_DENSITY_K = 5.23;

const FIELD_BULGE_DEPTH = 140;
const LEGEND_MARGIN = 170; // horizontal space reserved outside each field for its legend text

const LEGEND_SWATCH_R = 5;
const LEGEND_FONT_SIZE = 12;
const CLUSTER_LABEL_FONT_SIZE = 15;
const CLUSTER_LABEL_MARGIN = 16; // gap between a cluster's outer edge and its label
const ACTIVE_LABEL_FONT_SIZE = 14;

// Same radius formula as clusterPoint's own layout — used to place each
// cluster's label just outside its actual footprint, which varies with
// group size, rather than a fixed offset that only clears small clusters.
function clusterRadius(n) {
  return CLUSTER_DENSITY_K * Math.sqrt(Math.max(n, 1));
}

// The center circle's radius scales with its own dot count (same density
// formula as clusterRadius) instead of always claiming the full space the
// layout allots it — a narrow population segment (e.g. Veterans) gets a
// smaller, still-densely-packed circle rather than the same fixed
// footprint with its dots stretched thin. Capped at `maxRadius` (the
// space actually available in the scene) so a segment at least as large
// as "All Population" doesn't grow into the clusters/fields around it.
function centerRadiusFor(n, maxRadius) {
  return Math.min(CENTER_DENSITY_K * Math.sqrt(Math.max(n, 1)), maxRadius);
}

// A resolveCell()-style {value, marker} cell -> display text. A suppressed
// cell shows its marker ("*"/"**"), never a coerced 0 — the same rule
// KpiCard/every other chart in this app follows.
function formatCell(cell) {
  if (!cell) return "";
  if (cell.marker) return cell.marker;
  return (cell.value ?? 0).toLocaleString();
}

export const INFLOW_REASONS = ["newly_homeless", "return_from_housed", "return_from_inactive"];
export const OUTFLOW_REASONS = ["permanently_housed", "inactive", "deceased"];

export const INFLOW_LABELS = {
  newly_homeless: "Newly Homeless",
  return_from_housed: "Return from Housed",
  return_from_inactive: "Return from Inactive",
};
export const OUTFLOW_LABELS = {
  permanently_housed: "Permanently Housed",
  inactive: "Inactive",
  deceased: "Deceased",
};

// Slow, deliberate pacing so a viewer can actually watch each step happen.
const FLIGHT_PHASE1_MS = 2800; // field -> reason cluster
// Cluster labels fade in/out over FADE_MS at each end of this window (see
// showClusterLabel), so the fully-legible reading time is DWELL - FADE_MS
// — sized generously here (~2.5s) since there are six labels to scan.
const FLIGHT_DWELL_MS = 3400; // hold at the cluster so group sizes/labels can be compared
const FLIGHT_PHASE2_MS = 2800; // cluster -> settled position
export const FLIGHT_MS = FLIGHT_PHASE1_MS + FLIGHT_DWELL_MS + FLIGHT_PHASE2_MS;
const SNAP_MS = 3000;

// How long, at the very end of phase 2, the traveler crossfades into the
// resting dot already sitting at its destination (see landTraveler below).
const FADE_MS = 900;

function dotCount(cell, unitSize) {
  return Math.max(0, Math.round((cell?.value ?? 1) / unitSize));
}

// A thin, nearly-flat arc: just a shallow slice of a MUCH larger circle
// (a few degrees wide), not a full half-disc. `px,py` is the pivot point
// closest to the center of the scene; the field bulges gently away from it.
function semicircleLayout(n, { px, py, chordHeight, angleDeg, bulgeDepth, side }) {
  const angleSpan = (angleDeg * Math.PI) / 180;
  const hugeR = chordHeight / (2 * Math.sin(angleSpan / 2));
  const centerX = side === "left" ? px - hugeR : px + hugeR;
  const baseAngle = side === "left" ? 0 : Math.PI;
  const startAngle = baseAngle - angleSpan / 2;
  const endAngle = baseAngle + angleSpan / 2;

  const points = [];
  let ringR = Math.max(FIELD_RING_GAP, hugeR - bulgeDepth);
  while (points.length < n) {
    const capacity = Math.max(1, Math.floor((angleSpan * ringR) / FIELD_RING_GAP));
    const count = Math.min(capacity, n - points.length);
    for (let i = 0; i < count; i++) {
      const t = count === 1 ? 0.5 : i / (count - 1);
      const angle = startAngle + t * angleSpan;
      points.push({ x: centerX + ringR * Math.cos(angle), y: py + ringR * Math.sin(angle) });
    }
    ringR += FIELD_RING_GAP;
    if (ringR > hugeR + bulgeDepth * 4) break; // safety valve, should never trigger
  }
  return points;
}

// Phyllotaxis (golden-angle spiral) packing, normalized so the whole set
// of n points always sits inside maxRadius regardless of n. Because the
// radius term depends on n, a dot's position shifts slightly whenever n
// changes month to month — a deliberate "breathing" effect of the stock.
function spiralPoint(i, n, { cx, cy, maxRadius }) {
  const r = n <= 1 ? 0 : maxRadius * Math.sqrt((i + 0.5) / n);
  const angle = i * GOLDEN_ANGLE;
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
}

// A small staging cluster for one reason group: same phyllotaxis packing as
// the center circle, but its footprint grows with sqrt(group size) —
// constant dot density, so a bigger reason group reads as a visibly bigger
// cluster (area proportional to count), letting relative sizes be compared
// while dots dwell there mid-flight.
function clusterPoint(i, n, { x, y }) {
  return spiralPoint(i, n, { cx: x, cy: y, maxRadius: clusterRadius(n) });
}

// A tiny, organic idle wobble applied via CSS transform (not cx/cy), so it
// layers independently on top of D3's own position transitions rather than
// fighting them for the same attribute — applies whether a dot is resting
// or actively mid-flight. Randomized per-dot duration/delay/direction (via
// CSS custom properties consumed by the shared `flow-float` keyframes, see
// layout.css) keeps hundreds of dots from breathing in unison.
function applyFloat(selection) {
  return selection
    .style("--float-dur", () => `${(2.4 + Math.random() * 2.2).toFixed(2)}s`)
    .style("--float-delay", () => `-${(Math.random() * 4).toFixed(2)}s`)
    .style("--fx", () => (Math.random() * 2 - 1).toFixed(2))
    .style("--fy", () => (Math.random() * 2 - 1).toFixed(2));
}

function drawSideLegend(svg, className, items, { swatchX, textX }) {
  const g = svg.append("g").attr("class", className);
  const rows = g.selectAll("g.legend-row").data(items).join("g").attr("class", "legend-row");
  rows
    .append("circle")
    .attr("r", LEGEND_SWATCH_R)
    .attr("cx", swatchX)
    .attr("cy", (d) => d.y)
    .attr("fill", (d) => d.color);
  rows
    .append("text")
    .attr("x", textX)
    .attr("y", (d) => d.y)
    .attr("dy", "0.35em")
    .attr("font-size", LEGEND_FONT_SIZE)
    .attr("fill", "var(--text-dark)")
    .text((d) => d.label);
}

// Sends a reason-colored traveler from `from` through a staging cluster,
// dwells, then to `to`, where it crossfades into whatever's resting there
// underneath (gray on the right; on the left/center, see the delayed
// resting-dot construction in the per-step effect below, which makes sure
// nothing is actually resting there yet until this same crossfade window).
// Colors are CSS custom properties (var(--chart-N)), which D3 can't
// interpolate between directly (it would just snap), so instead of
// animating `fill`, the traveler fades its own opacity to 0 as the
// resting dot fades to 1 — the two overlapping, alpha-blended circles
// read as a smooth color fade with no lingering colored trail.
//
// `node`, if given, is a real existing circle element to reuse (e.g. a
// dot that was just resting in the center and is now departing) instead
// of creating a new one — so a dot is never simultaneously "still there"
// and "also flying away" as two separate elements.
function flyTraveler(travelerGroup, { node, className, color, from, clusterPos, to }) {
  if (node) travelerGroup.node().appendChild(node);
  const selection = node ? d3.select(node).interrupt() : travelerGroup.append("circle").attr("r", CENTER_DOT_R);
  const el = applyFloat(
    selection
      .attr("class", `${className} flow-float`)
      .attr("fill", color)
      .attr("cx", from.x)
      .attr("cy", from.y)
      // Explicit starting value: the "fade" transition below interpolates
      // opacity from whatever this attribute currently reads as, and an
      // unset attribute isn't a usable numeric start — it would just snap
      // instead of fading.
      .attr("opacity", 1)
  );

  el.transition()
    .duration(FLIGHT_PHASE1_MS)
    .ease(d3.easeCubicInOut)
    .attr("cx", clusterPos.x)
    .attr("cy", clusterPos.y)
    .transition()
    .duration(FLIGHT_DWELL_MS)
    .transition()
    .duration(FLIGHT_PHASE2_MS)
    .ease(d3.easeCubicInOut)
    .attr("cx", to.x)
    .attr("cy", to.y);

  el.transition("fade")
    .delay(FLIGHT_PHASE1_MS + FLIGHT_DWELL_MS + Math.max(0, FLIGHT_PHASE2_MS - FADE_MS))
    .duration(Math.min(FADE_MS, FLIGHT_PHASE2_MS))
    .attr("opacity", 0)
    .on("end", function () {
      d3.select(this).remove();
    });
}

export default function FlowScrubberChart({
  monthlySteps,
  activeIndex,
  direction,
  unitSize = 20,
  fieldSize,
  width = 1200,
  height = 560,
}) {
  const svgRef = useRef(null);
  // Persistent per-dot identity (not index-based — see the per-step effect)
  // so a specific dot can be tracked, reused, and reparented across a
  // step's animation instead of the center set being wholesale
  // recomputed-and-redrawn each time.
  const centerDotsRef = useRef([]); // [{id}]
  const nextIdRef = useRef(0);
  const prevIndexRef = useRef(null);
  // Scheduled update of the center count label for a sequential-forward
  // step (fires once dots finish settling, see below) — stopped/replaced
  // if a new step arrives before it fires, so a stale scheduled update
  // can't clobber a later month's label.
  const centerLabelTimerRef = useRef(null);

  const geom = useMemo(() => {
    const cy = height / 2;
    const centerRadius = Math.min(width, height) * 0.2;
    const centerCx = width / 2;
    const leftPivotX = LEGEND_MARGIN + FIELD_BULGE_DEPTH;
    const rightPivotX = width - leftPivotX;
    const fieldGeom = { chordHeight: height * 0.85, angleDeg: 5, bulgeDepth: FIELD_BULGE_DEPTH };

    const clusterSpread = centerRadius * 1.3;
    const inflowClusterX = (leftPivotX + (centerCx - centerRadius)) / 2;
    const outflowClusterX = (rightPivotX + (centerCx + centerRadius)) / 2;

    return {
      left: { px: leftPivotX, py: cy, side: "left", ...fieldGeom },
      right: { px: rightPivotX, py: cy, side: "right", ...fieldGeom },
      center: { cx: centerCx, cy, maxRadius: centerRadius },
      inflowClusters: {
        newly_homeless: { x: inflowClusterX, y: cy - clusterSpread },
        return_from_housed: { x: inflowClusterX, y: cy },
        return_from_inactive: { x: inflowClusterX, y: cy + clusterSpread },
      },
      outflowClusters: {
        permanently_housed: { x: outflowClusterX, y: cy - clusterSpread },
        inactive: { x: outflowClusterX, y: cy },
        deceased: { x: outflowClusterX, y: cy + clusterSpread },
      },
    };
  }, [width, height]);

  const leftField = useMemo(() => semicircleLayout(fieldSize, geom.left), [fieldSize, geom.left]);
  const rightField = useMemo(() => semicircleLayout(fieldSize, geom.right), [fieldSize, geom.right]);

  // Scene setup: static gray fields + legends, drawn once per dataset/geometry change.
  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    applyFloat(
      svg
        .append("g")
        .attr("class", "left-field")
        .selectAll("circle")
        .data(leftField)
        .join("circle")
        .attr("class", "flow-float")
        .attr("r", FIELD_DOT_R)
        .attr("cx", (d) => d.x)
        .attr("cy", (d) => d.y)
        .attr("fill", FIELD_GRAY)
    );

    applyFloat(
      svg
        .append("g")
        .attr("class", "right-field")
        .selectAll("circle")
        .data(rightField)
        .join("circle")
        .attr("class", "right-dot flow-float")
        .attr("r", FIELD_DOT_R)
        .attr("cx", (d) => d.x)
        .attr("cy", (d) => d.y)
        .attr("fill", FIELD_GRAY)
    );

    svg.append("g").attr("class", "center-field");
    svg.append("g").attr("class", "travelers");
    svg.append("g").attr("class", "cluster-labels");

    drawSideLegend(
      svg,
      "legend-inflow",
      INFLOW_REASONS.map((r) => ({ color: FLOW_COLORS[r], label: INFLOW_LABELS[r], y: geom.inflowClusters[r].y })),
      { swatchX: 14, textX: 26 }
    );
    drawSideLegend(
      svg,
      "legend-outflow",
      OUTFLOW_REASONS.map((r) => ({ color: FLOW_COLORS[r], label: OUTFLOW_LABELS[r], y: geom.outflowClusters[r].y })),
      { swatchX: geom.right.px + geom.right.bulgeDepth + 22, textX: geom.right.px + geom.right.bulgeDepth + 34 }
    );

    // Directly under the center circle (not the far-off corner legends) so
    // it reads as labeling that circle specifically — its live count is
    // filled in by the per-step effect, timed to when each step's
    // dots actually finish settling (see centerLabelTimerRef).
    svg
      .append("text")
      .attr("class", "center-count-label")
      .attr("x", geom.center.cx)
      .attr("y", geom.center.cy + geom.center.maxRadius + 24)
      .attr("text-anchor", "middle")
      .attr("font-size", ACTIVE_LABEL_FONT_SIZE)
      .attr("font-weight", 600)
      .attr("fill", "var(--text-navy)")
      .text(ACTIVE_LABEL);

    centerDotsRef.current = [];
    nextIdRef.current = 0;
    prevIndexRef.current = null;
    centerLabelTimerRef.current?.stop();
    centerLabelTimerRef.current = null;
  }, [leftField, rightField, width, height, geom]);

  // Per-step transition: animate a sequential forward step, snap otherwise.
  useEffect(() => {
    const step = monthlySteps[activeIndex];
    if (!step) return; // out-of-range during a transitional render (e.g. filter just changed)
    const svg = d3.select(svgRef.current);
    const centerGroup = svg.select("g.center-field");
    const travelerGroup = svg.select("g.travelers");
    const clusterLabelGroup = svg.select("g.cluster-labels");
    if (centerGroup.empty()) return;

    // Always start from a clean slate: cancel/remove any in-flight
    // travelers so rapid stepping degrades to a snap instead of stacking.
    travelerGroup.selectAll("circle").interrupt().interrupt("fade").remove();
    // Interrupting also forces opacity back to 1 — an arrival dot's
    // resting circle starts at opacity 0 and only reaches 1 via a
    // delayed transition scheduled to fire near the end of the flight
    // (see the arrivals loop below); if the next step starts (as it
    // normally does, well before a 9s flight completes) before that
    // transition has run, interrupting it alone would leave the dot
    // stuck invisible forever, since nothing else ever revisits a
    // "remaining" dot's opacity in later steps. From a new step's
    // perspective every existing center-dot should read as settled/
    // visible regardless of where its own animation was interrupted.
    centerGroup.selectAll("circle.center-dot").interrupt().attr("opacity", 1);
    clusterLabelGroup.selectAll("text").interrupt().remove();
    centerLabelTimerRef.current?.stop();
    centerLabelTimerRef.current = null;

    const centerCountLabel = svg.select("text.center-count-label").interrupt();

    const targetCount = dotCount(step.activeTotal, unitSize);
    const prevIdx = prevIndexRef.current;
    const isSequentialForward = prevIdx !== null && direction === "forward" && activeIndex === prevIdx + 1;

    // First render, backward step, or an arbitrary jump (mobile slider):
    // recompute canonical state for this month directly, no flight, and no
    // continuity with whatever dot identities existed before — the side
    // fields have no persisted history to restore either, they're always
    // just the static gray backdrop.
    const snapRenderCenter = (n, { duration }) => {
      const dots = d3.range(n).map(() => ({ id: nextIdRef.current++ }));
      centerDotsRef.current = dots;
      const centerGeom = { ...geom.center, maxRadius: centerRadiusFor(n, geom.center.maxRadius) };
      centerGroup
        .selectAll("circle.center-dot")
        .data(dots, (d) => d.id)
        .join(
          (enter) =>
            applyFloat(
              enter
                .append("circle")
                .attr("class", "center-dot flow-float")
                .attr("r", CENTER_DOT_R)
                .attr("fill", ACTIVE_COLOR)
                .attr("cx", (d, i) => spiralPoint(i, n, centerGeom).x)
                .attr("cy", (d, i) => spiralPoint(i, n, centerGeom).y)
            ),
          (update) =>
            update
              .transition()
              .duration(duration)
              .ease(d3.easeCubicInOut)
              .attr("cx", (d, i) => spiralPoint(i, n, centerGeom).x)
              .attr("cy", (d, i) => spiralPoint(i, n, centerGeom).y),
          (exit) => exit.remove()
        );
    };

    if (!isSequentialForward) {
      snapRenderCenter(targetCount, { duration: SNAP_MS });
      centerCountLabel.attr("opacity", 1).text(`Active: ${formatCell(step.activeTotal)}`);
    } else {
      // Sequential forward step: every dot in the center has a persistent
      // id (see centerDotsRef), so departures and arrivals are real,
      // individually tracked add/remove events synced to the flight
      // animation, not an instant jump to the new total with a merely
      // decorative traveler drawn alongside it. Specifically:
      //  - a departing dot IS the same circle element that was resting in
      //    the center — reparented and flown out, never a separate
      //    duplicate — so it only visually leaves once its travel
      //    animation actually does.
      //  - an arriving dot's resting position is created invisible
      //    (opacity 0) and only fades in during the crossfade at the end
      //    of its traveler's flight, so it doesn't appear to "already be
      //    there" before the traveler carrying it lands.
      //  - dots that are neither departing nor arriving just reflow to
      //    their slot in the new, larger/smaller layout, same as before.
      const outflowByReason = Object.fromEntries(
        OUTFLOW_REASONS.map((r) => [r, dotCount(step.outflow[r], unitSize)])
      );

      // A count label beside each reason cluster, visible only while its
      // dots are actually dwelling there as individual bubbles — fades in
      // as phase 1 (field -> cluster) finishes, holds through the dwell,
      // and fades back out as phase 2 (cluster -> destination) begins.
      // Positioned outward (inflow clusters label to their left, toward
      // the left field; outflow clusters label to their right, toward the
      // right field) at a distance based on the cluster's own radius —
      // a fixed offset would sit inside/on top of a large cluster's dots
      // and be illegible, since cluster radius grows with group size.
      const showClusterLabel = (cluster, cell, n, side) => {
        const x = side === "left" ? cluster.x - clusterRadius(n) - CLUSTER_LABEL_MARGIN : cluster.x + clusterRadius(n) + CLUSTER_LABEL_MARGIN;
        clusterLabelGroup
          .append("text")
          .attr("x", x)
          .attr("y", cluster.y)
          .attr("dy", "0.35em")
          .attr("text-anchor", side === "left" ? "end" : "start")
          .attr("font-size", CLUSTER_LABEL_FONT_SIZE)
          .attr("font-weight", 700)
          .attr("fill", "var(--text-dark)")
          .attr("opacity", 0)
          .text(formatCell(cell))
          .transition()
          .delay(FLIGHT_PHASE1_MS - FADE_MS)
          .duration(FADE_MS)
          .attr("opacity", 1)
          .transition()
          .delay(FLIGHT_DWELL_MS - FADE_MS)
          .duration(FADE_MS)
          .attr("opacity", 0)
          .on("end", function () {
            d3.select(this).remove();
          });
      };
      OUTFLOW_REASONS.forEach((r) => showClusterLabel(geom.outflowClusters[r], step.outflow[r], outflowByReason[r], "right"));
      INFLOW_REASONS.forEach((r) => showClusterLabel(geom.inflowClusters[r], step.inflow[r], dotCount(step.inflow[r], unitSize), "left"));

      const currentDots = centerDotsRef.current;
      const outflowTotalRaw = Object.values(outflowByReason).reduce((a, b) => a + b, 0);
      const outflowTotal = Math.min(outflowTotalRaw, currentDots.length);

      // No real per-person identity to prioritize by, so departures are a
      // random sample of the current set rather than always "the last N".
      const departures = d3.shuffle(currentDots.slice()).slice(0, outflowTotal);
      const departureIds = new Set(departures.map((d) => d.id));
      const remaining = currentDots.filter((d) => !departureIds.has(d.id));

      const arrivals = [];
      for (const reason of INFLOW_REASONS) {
        const n = dotCount(step.inflow[reason], unitSize);
        for (let i = 0; i < n; i++) arrivals.push({ id: nextIdRef.current++ });
      }

      // Departures first, so they're reparented out of g.center-field
      // before the remaining-dots join below runs — otherwise it would
      // see them as an "exit" (they're not in `remaining`) and remove
      // them outright, before they get a chance to fly anywhere.
      const priorNodes = new Map();
      centerGroup.selectAll("circle.center-dot").each(function (d) {
        priorNodes.set(d.id, this);
      });

      // remaining.length + arrivals.length won't always exactly equal
      // targetCount: outflowTotal/inflowTotal are each a sum of three
      // independently-rounded reason counts, so they can drift by a dot or
      // two from targetCount's own independent rounding of the true
      // activeTotal. Reconcile silently (added/removed with no traveler
      // animation, matching the size of the drift — at most a dot or two)
      // rather than let it compound across steps.
      let silentAdditions = [];
      const drift = targetCount - (remaining.length + arrivals.length);
      if (drift > 0) {
        silentAdditions = d3.range(drift).map(() => ({ id: nextIdRef.current++ }));
      } else if (drift < 0) {
        const dropIds = new Set(remaining.slice(0, -drift).map((d) => d.id));
        for (const id of dropIds) priorNodes.get(id)?.remove();
        for (let i = remaining.length - 1; i >= 0; i--) {
          if (dropIds.has(remaining[i].id)) remaining.splice(i, 1);
        }
      }

      const finalDots = [...remaining, ...arrivals, ...silentAdditions];
      centerDotsRef.current = finalDots;
      const centerGeom = { ...geom.center, maxRadius: centerRadiusFor(finalDots.length, geom.center.maxRadius) };

      // Each dot's spiral SLOT (not its position in `finalDots`) is what
      // spiralPoint's index arg should be — spiralPoint's uniform-density
      // packing only holds if the full 0..n-1 range is spread across
      // everyone. Using array order directly would put every "remaining"
      // dot at the low end (small radius) and every "arrivals" dot at the
      // high end (large radius) every single step; since remaining always
      // carries the same relative order forward, survivors from months
      // ago stay pinned near the lowest indices while each new cohort
      // gets pushed further out — after a few months that reads as a
      // shrinking inner cluster of old survivors surrounded by a
      // separate outer ring of everyone newer, not one evenly-filled
      // disc. A fresh random shuffle of slots each step (not persisted —
      // it doesn't need to be, only positions matter) keeps the fill
      // uniform regardless of how long a dot has been "remaining".
      const slots = d3.shuffle(d3.range(finalDots.length));
      const slotById = new Map(finalDots.map((d, k) => [d.id, slots[k]]));

      let departPlaced = 0;
      departureLoop: for (const reason of OUTFLOW_REASONS) {
        const n = outflowByReason[reason];
        const cluster = geom.outflowClusters[reason];
        for (let i = 0; i < n; i++) {
          if (departPlaced >= departures.length) break departureLoop;
          const dot = departures[departPlaced++];
          const node = priorNodes.get(dot.id);
          if (!node) continue; // shouldn't happen, but don't break the step if it does
          flyTraveler(travelerGroup, {
            node,
            className: "traveler-out",
            color: FLOW_COLORS[reason],
            from: { x: +node.getAttribute("cx"), y: +node.getAttribute("cy") },
            clusterPos: clusterPoint(i, n, cluster),
            to: rightField[Math.floor(Math.random() * rightField.length)],
          });
        }
      }

      // Remaining dots: reflow to their slot in the new layout. A normal
      // update-only join — every id here already exists and stays a
      // center-dot, so there's no enter/exit involved. Paced to
      // FLIGHT_PHASE1_MS (not the full flight) so the center circle
      // finishes resettling around the same time travelers reach their
      // clusters, instead of still visibly drifting for the whole dwell.
      centerGroup
        .selectAll("circle.center-dot")
        .data(remaining, (d) => d.id)
        .transition()
        .duration(FLIGHT_PHASE1_MS)
        .ease(d3.easeCubicInOut)
        .attr("cx", (d) => spiralPoint(slotById.get(d.id), finalDots.length, centerGeom).x)
        .attr("cy", (d) => spiralPoint(slotById.get(d.id), finalDots.length, centerGeom).y);

      // Arrivals: a traveler flies in from the field as before, plus an
      // invisible resting dot at its landing spot that only fades in
      // during the same crossfade the traveler fades out in — see
      // flyTraveler's docstring.
      let arrivalIdx = 0;
      for (const reason of INFLOW_REASONS) {
        const n = dotCount(step.inflow[reason], unitSize);
        const cluster = geom.inflowClusters[reason];
        for (let i = 0; i < n; i++) {
          const dot = arrivals[arrivalIdx++];
          const finalPos = spiralPoint(slotById.get(dot.id), finalDots.length, centerGeom);

          applyFloat(
            centerGroup
              .append("circle")
              .datum(dot)
              .attr("class", "center-dot flow-float")
              .attr("r", CENTER_DOT_R)
              .attr("fill", ACTIVE_COLOR)
              .attr("cx", finalPos.x)
              .attr("cy", finalPos.y)
              .attr("opacity", 0)
          )
            .transition()
            .delay(FLIGHT_PHASE1_MS + FLIGHT_DWELL_MS + Math.max(0, FLIGHT_PHASE2_MS - FADE_MS))
            .duration(Math.min(FADE_MS, FLIGHT_PHASE2_MS))
            .attr("opacity", 1);

          flyTraveler(travelerGroup, {
            className: "traveler-in",
            color: FLOW_COLORS[reason],
            from: leftField[Math.floor(Math.random() * leftField.length)],
            clusterPos: clusterPoint(i, n, cluster),
            to: finalPos,
          });
        }
      }

      // Silent rounding-drift correction (see above) — rendered instantly,
      // no traveler, since it isn't tied to any specific reason/person.
      silentAdditions.forEach((dot) => {
        const pos = spiralPoint(slotById.get(dot.id), finalDots.length, centerGeom);
        applyFloat(
          centerGroup
            .append("circle")
            .datum(dot)
            .attr("class", "center-dot flow-float")
            .attr("r", CENTER_DOT_R)
            .attr("fill", ACTIVE_COLOR)
            .attr("cx", pos.x)
            .attr("cy", pos.y)
        );
      });

      // The count is only actually true at the very beginning (last
      // month's settled total) and the very end (this month's) of the
      // flight — anywhere in between, dots are visibly leaving/arriving
      // and a static old number sitting there reads as wrong/stale. Fade
      // it out right away, then back in with the new value once dots
      // finish settling.
      centerCountLabel.transition().duration(FADE_MS / 2).attr("opacity", 0);
      centerLabelTimerRef.current = d3.timeout(() => {
        centerCountLabel
          .text(`Active: ${formatCell(step.activeTotal)}`)
          .transition()
          .duration(FADE_MS / 2)
          .attr("opacity", 1);
      }, FLIGHT_MS);
    }

    prevIndexRef.current = activeIndex;
  }, [monthlySteps, activeIndex, direction, unitSize, leftField, rightField, geom]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
