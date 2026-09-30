import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { sankey } from "d3-sankey";
import { FLOW_COLORS } from "../../lib/flowColors.js";
import { INFLOW_BUCKET_KEYS, OUTFLOW_BUCKET_KEYS } from "../../lib/sankeyData.js";
import { PRIMARY_SUPPRESSION_MARKER, SECONDARY_SUPPRESSION_MARKER } from "../../lib/loadData.js";
import { clearTooltip, createTooltip } from "../../lib/tooltip.js";

export const ACTIVE_COLOR = "var(--chart-2)";

const NODE_LABELS = {
  already_active: "Already Active",
  newly_homeless: "Newly Homeless",
  return_from_housed: "Return from Housed",
  return_from_inactive: "Return from Inactive",
  still_active: "Still Active",
  aged_out: "Aged Out",
  permanently_housed: "Permanently Housed",
  inactive: "Inactive",
  deceased: "Deceased",
};

const ACTIVE_NODE_IDS = new Set(["already_active", "still_active"]);

// Suppressed cells never reveal a number (see resolveCell). A primary-
// suppressed ("*") link keeps a small, fixed nominal width on both ends —
// it stays visibly present instead of vanishing (0, which would
// misrepresent it as truly empty) or overstating it, same convention the
// old dot chart used for a suppressed cell's dot count. A secondary-
// suppressed ("**") link is treated differently — see linkWidths below —
// so this nominal only actually applies to primary and to visible cells
// (where it's unused, since magnitude() returns the true value instead).
const SUPPRESSED_NOMINAL = 1;

function magnitude(cell) {
  if (!cell) return 0;
  return cell.marker ? SUPPRESSED_NOMINAL : cell.value ?? 0;
}

function formatCell(cell) {
  if (!cell) return "";
  if (cell.marker) return cell.marker;
  return (cell.value ?? 0).toLocaleString();
}

// The max true value a primary-suppressed ("*") cell can hold — HUD
// small-cell suppression masks any nonzero count under this (see
// pipeline/config.py's SUPPRESSION_THRESHOLD = 11), so 10 is the largest
// it could possibly be.
const MAX_PRIMARY_SUPPRESSED_VALUE = 10;

// Share of the link's own inflow node that this link represents, e.g.
// "(18% of Newly Homeless inflow)" alongside the link's count. Only shown
// when both the link and its source node have real (non-suppressed)
// values — a suppressed marker isn't a true count, so dividing by or into
// one would produce a percentage that misrepresents the actual share.
function formatLinkPercentOfInflow(d) {
  if (d.source.cell?.marker) return "";
  if (!d.cell.marker) {
    const linkValue = d.cell.value ?? 0;
    const inflowTotal = d.source.cell?.value ?? 0;
    if (!inflowTotal) return "";
    const pct = Math.round((linkValue / inflowTotal) * 100);
    return ` <span style="font-style:italic">(${pct}% of ${d.source.label} inflow)</span>`;
  }
  if (d.cell.marker === SECONDARY_SUPPRESSION_MARKER) {
    return formatSecondarySuppressedPercentEstimate(d);
  }
  return "";
}

// A secondary-suppressed ("**") link's own true value isn't published, but
// a lower bound can still be estimated from numbers that ARE public: the
// inflow node's own total, minus every visible sibling link, minus the
// largest every primary-suppressed ("*") sibling could possibly be
// (MAX_PRIMARY_SUPPRESSED_VALUE each). Since a smaller true primary value
// would only leave MORE, not less, for this cell, that's a floor on the
// secondary cell's share — not its exact value. Bails out (returns "") if
// any sibling link carries an unrecognized marker (e.g.
// INSUFFICIENT_POPULATION_MARKER) this estimate doesn't account for, or if
// the estimate comes out non-positive (the bound isn't actually
// informative).
function formatSecondarySuppressedPercentEstimate(d) {
  const inflowTotal = d.source.cell?.value ?? 0;
  if (!inflowTotal) return "";
  const siblingLinks = d.source.sourceLinks ?? [];
  let visibleSum = 0;
  let primaryCount = 0;
  for (const link of siblingLinks) {
    const marker = link.cell?.marker;
    if (!marker) {
      visibleSum += link.cell?.value ?? 0;
    } else if (marker === PRIMARY_SUPPRESSION_MARKER) {
      primaryCount += 1;
    } else if (marker !== SECONDARY_SUPPRESSION_MARKER) {
      return "";
    }
  }
  const estimate = inflowTotal - visibleSum - primaryCount * MAX_PRIMARY_SUPPRESSED_VALUE;
  if (estimate <= 0) return "";
  const rawPct = (estimate / inflowTotal) * 100;
  const pct = Math.round(rawPct / 5) * 5;
  return ` <span style="font-style:italic">(about ${pct}% of ${d.source.label} inflow, rounded to the nearest 5%)</span>`;
}

function nodeColor(id) {
  return ACTIVE_NODE_IDS.has(id) ? ACTIVE_COLOR : FLOW_COLORS[id];
}

// One node per inflow/outflow bucket — already_active/still_active listed
// first in each column (see INFLOW_BUCKET_KEYS/OUTFLOW_BUCKET_KEYS) so
// they land at the top when nodeSort is disabled below, running parallel
// to each other across the top of the diagram. One link per (inflow,
// outflow) pair with at least a nominal magnitude — e.g. "of the people
// newly homeless this period, how many ended up still active vs.
// permanently housed" — a direct trace from arrival reason to outcome,
// instead of pooling everyone through a single middle node.
//
// `outflowKeys` is the caller's own choice of which outflow buckets to
// render — aged_out is always 0 for every population but YYA (see
// build_flow.py's _partition_by_individual), so the caller filters it out
// rather than showing a permanently-empty node on every other population.
function buildGraph({ startActive, endActive, inflow, outflow, pairs }, outflowKeys) {
  const cellFor = (id) => (id === "already_active" ? startActive : id === "still_active" ? endActive : (inflow[id] ?? outflow[id]));

  // fixedValue pins each node's own bar height to its own true (or nominal,
  // if suppressed) magnitude — d3-sankey otherwise sizes a node from the
  // sum of its connecting links instead, which can be far smaller than the
  // node's own printed value: a demographic slice small enough that a
  // node's aggregate cell is still visible, but several of the individual
  // inflow-to-outflow pairs feeding it are each separately suppressed
  // (and so each contribute only SUPPRESSED_NOMINAL), would otherwise
  // render a bar that looks tiny next to a much larger printed number.
  const nodes = [
    ...INFLOW_BUCKET_KEYS.map((id) => ({ id, label: NODE_LABELS[id], cell: cellFor(id), fixedValue: magnitude(cellFor(id)) })),
    ...outflowKeys.map((id) => ({ id, label: NODE_LABELS[id], cell: cellFor(id), fixedValue: magnitude(cellFor(id)) })),
  ];
  const fixedValueById = new Map(nodes.map((n) => [n.id, n.fixedValue]));

  const candidateLinks = [];
  for (const inflowKey of INFLOW_BUCKET_KEYS) {
    for (const outflowKey of outflowKeys) {
      const cell = pairs[`${inflowKey}_to_${outflowKey}`];
      if (magnitude(cell) > 0) candidateLinks.push({ source: inflowKey, target: outflowKey, cell });
    }
  }

  // Which nodes have at least one secondary-suppressed link touching them —
  // determines, per node, whether the secondary links or (if none are
  // present) the primary links are the ones that expand to fill leftover
  // space; whichever kind ISN'T expanding at a given node stays at the
  // small fixed nominal.
  const nodesWithSecondary = new Set();
  for (const l of candidateLinks) {
    if (l.cell.marker === SECONDARY_SUPPRESSION_MARKER) {
      nodesWithSecondary.add(l.source);
      nodesWithSecondary.add(l.target);
    }
  }

  // Whether `cell`'s link expands to fill leftover space at this
  // particular end (`nodeId`) rather than sitting at the flat nominal.
  // Secondary-suppressed links always do. Primary-suppressed links only
  // do when their node has NO secondary-suppressed link of its own to do
  // that job instead — otherwise every primary link there stays small,
  // per the deliberate "keep primary suppression small, let secondary
  // suppression expand" split.
  function isExpandingAt(nodeId, cell) {
    if (cell.marker === SECONDARY_SUPPRESSION_MARKER) return true;
    if (cell.marker === PRIMARY_SUPPRESSION_MARKER) return !nodesWithSecondary.has(nodeId);
    return false;
  }

  // The rendered width, at ONE of a link's two ends, for whichever links
  // are "expanding" at that node (see isExpandingAt): that node's own true
  // total, minus everything else already accounted for (visible links at
  // their true value, non-expanding primary links at their small fixed
  // nominal), split evenly across however many links are expanding there.
  // Computed independently per end (a link's source node and target node
  // can each have a different amount left over, and even a different
  // reason for expanding) — the rendered ribbon (see taperedLinkPath)
  // tapers between the two rather than forcing one uniform width that's
  // only correct on one side.
  //
  // Safe to do (doesn't reveal a suppressed cell's real value) in both
  // cases: apply_crosstab_secondary_suppression guarantees any node with a
  // primary-suppressed link also has at least one OTHER suppressed link
  // (primary or secondary) to share the unknown remainder with, so "what's
  // left" is always divided among 2+ genuinely unknown cells, never
  // assigned outright to a single one. For the primary-only case
  // specifically: secondary suppression is only skipped when those
  // primary-suppressed cells' true values aren't all tied at the 1-or-10
  // extreme (see suppression.py's rule (b)) — exactly the case where
  // knowing their sum still doesn't pin down the individual split, so
  // splitting that already-computable sum evenly for display doesn't
  // expose anything beyond what the visible total and siblings already do.
  function expandingWidthAt(nodeId) {
    const linksAtNode = candidateLinks.filter((l) => l.source === nodeId || l.target === nodeId);
    const expandingLinks = linksAtNode.filter((l) => isExpandingAt(nodeId, l.cell));
    if (expandingLinks.length === 0) return SUPPRESSED_NOMINAL;
    const accountedFor = linksAtNode.reduce(
      (sum, l) => (isExpandingAt(nodeId, l.cell) ? sum : sum + magnitude(l.cell)),
      0
    );
    const remaining = Math.max(0, (fixedValueById.get(nodeId) ?? 0) - accountedFor);
    return remaining / expandingLinks.length;
  }

  const links = candidateLinks.map((l) => {
    const sourceWidth = isExpandingAt(l.source, l.cell) ? expandingWidthAt(l.source) : magnitude(l.cell);
    const targetWidth = isExpandingAt(l.target, l.cell) ? expandingWidthAt(l.target) : magnitude(l.cell);
    return {
      source: l.source,
      target: l.target,
      cell: l.cell,
      sourceWidth,
      targetWidth,
      // Feeds d3-sankey's own link-stacking order/position within a node
      // (see computeLinkBreadths) — the two ends' widths only ever differ
      // for a tapered link, so their average is a reasonable single
      // stand-in for layout purposes; the actual rendered shape uses
      // sourceWidth/targetWidth directly, not this.
      value: (sourceWidth + targetWidth) / 2,
    };
  });

  return { nodes, links };
}

// Draws a ribbon as a filled shape (not a stroked centerline) so its two
// ends can independently take sourceWidth/targetWidth — a plain SVG stroke
// can't vary its own width along its length, which a uniform link doesn't
// need but a tapered (partly secondary-suppressed) one does. Same
// horizontal S-curve control points d3's own sankeyLinkHorizontal uses,
// just applied to both the top and bottom edges independently instead of
// one centerline.
// d3-sankey's own computeLinkBreadths stacks every link touching a node
// using ONE uniform link.width for both its source-side and target-side
// position (see d3-sankey/src/sankey.js) — correct for a uniform-width
// link, but wrong for a tapered one, whose sourceWidth and targetWidth can
// genuinely differ (see buildGraph's secondaryWidthAt). Left as d3
// computed it, every OTHER link sharing that node gets positioned as if
// the tapered link took up its averaged width at both ends, which is
// wrong at whichever end that average doesn't match — leaving a gap at
// one end of the stack and an overlap at the other, compounding for every
// later link in the same stack. Recomputed here instead, same algorithm
// as d3's own computeLinkBreadths, just reading sourceWidth/targetWidth
// (each scaled by ky) instead of the single link.width.
function recomputeLinkBreadths(nodes, ky) {
  for (const node of nodes) {
    let y0 = node.y0;
    for (const link of node.sourceLinks) {
      const w = link.sourceWidth * ky;
      link.y0 = y0 + w / 2;
      y0 += w;
    }
    let y1 = node.y0;
    for (const link of node.targetLinks) {
      const w = link.targetWidth * ky;
      link.y1 = y1 + w / 2;
      y1 += w;
    }
  }
}

// Two adjacent ribbons at the same node share a fill color and are each
// their own <path> — sized to exactly touch (see recomputeLinkBreadths),
// their abutting edges land on the same sub-pixel line, and the browser's
// anti-aliasing renders that shared edge as a partly-transparent seam
// (neither ribbon's fill "claims" it fully), showing as a thin light line
// even though the underlying geometry has no real gap. A small overlap
// (half a pixel into each neighbor) closes it — imperceptible on its own
// (same color/opacity on both sides), unlike the seam it replaces.
const SEAM_OVERLAP = 0.5;

// `ky` converts sourceWidth/targetWidth (raw person-count magnitudes) into
// the same pixel scale d3-sankey used for the node heights and its own
// (unused here) link.width — without it, a real value like "7,819" would
// be read as 7,819 *pixels* wide, ballooning every link into a solid block
// covering the whole chart instead of a proportionally-sized ribbon.
function taperedLinkPath(d, ky) {
  const x0 = d.source.x1;
  const x1 = d.target.x0;
  const xm = (x0 + x1) / 2;
  const sourceHalf = (d.sourceWidth * ky) / 2 + SEAM_OVERLAP;
  const targetHalf = (d.targetWidth * ky) / 2 + SEAM_OVERLAP;
  const topY0 = d.y0 - sourceHalf;
  const topY1 = d.y1 - targetHalf;
  const bottomY0 = d.y0 + sourceHalf;
  const bottomY1 = d.y1 + targetHalf;
  return (
    `M${x0},${topY0}C${xm},${topY0},${xm},${topY1},${x1},${topY1}` +
    `L${x1},${bottomY1}C${xm},${bottomY1},${xm},${bottomY0},${x0},${bottomY0}Z`
  );
}

const NODE_LABEL_FONT_SIZE = 12;
const NODE_COUNT_FONT_SIZE = 13;
const HEADLINE_LABEL_FONT_SIZE = 15;
const NODE_WIDTH = 18;
const NODE_PADDING = 16;

export default function FlowSankeyChart({ data, periodLabel, isFullYear, populationSegment, width = 960, height = 620 }) {
  const svgRef = useRef(null);
  // aged_out is only ever nonzero for the YYA population — hide the node
  // entirely for every other selection rather than showing a permanent 0.
  const outflowKeys = populationSegment === "yya" ? OUTFLOW_BUCKET_KEYS : OUTFLOW_BUCKET_KEYS.filter((id) => id !== "aged_out");

  useEffect(() => {
    if (!data) return;
    const margin = { top: 56, right: 170, bottom: 20, left: 170 };

    const { nodes: rawNodes, links: rawLinks } = buildGraph(data, outflowKeys);

    const svg = d3.select(svgRef.current);
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    // d3-sankey scales every node's height proportional to the graph's
    // total link value — with zero links (every cell's magnitude is 0,
    // e.g. a demographic slice suppressed/empty for this exact period)
    // that total is 0 and the layout divides by it, producing NaN
    // geometry (and console errors) instead of an empty diagram. Render
    // an explicit "no data" message instead of handing d3-sankey a graph
    // it can't lay out.
    if (rawLinks.length === 0) {
      svg
        .append("text")
        .attr("x", width / 2)
        .attr("y", height / 2)
        .attr("text-anchor", "middle")
        .attr("font-size", NODE_LABEL_FONT_SIZE)
        .attr("fill", "var(--text-gray)")
        .text("No data for this selection.");
      return;
    }

    const { nodes, links } = sankey()
      .nodeId((d) => d.id)
      .nodeWidth(NODE_WIDTH)
      .nodePadding(NODE_PADDING)
      // Preserves input order within each column (already_active/
      // still_active first) instead of d3-sankey's default "reorder to
      // minimize crossings" — see buildGraph's own comment on why: they
      // should stay pinned to the top, running parallel, not drift based
      // on link layout.
      .nodeSort(null)
      .extent([
        [margin.left, margin.top],
        [width - margin.right, height - margin.bottom],
      ])({
      nodes: rawNodes.map((d) => ({ ...d })),
      links: rawLinks.map((d) => ({ ...d })),
    });

    const leftX = nodes.find((n) => INFLOW_BUCKET_KEYS.includes(n.id)).x0;
    const rightX = nodes.find((n) => OUTFLOW_BUCKET_KEYS.includes(n.id)).x1;

    // d3-sankey computed its own link.width from the `value` (average of
    // sourceWidth/targetWidth) we fed it as link.value * ky, for some
    // internal scale constant ky it never exposes directly — recovered
    // here from any one link's own before/after ratio (the same ky applies
    // graph-wide) so taperedLinkPath can apply that identical scale to
    // sourceWidth/targetWidth individually.
    const kyLink = links.find((l) => l.value > 0);
    const ky = kyLink ? kyLink.width / kyLink.value : 1;
    recomputeLinkBreadths(nodes, ky);

    const container = svgRef.current.parentElement;
    clearTooltip(container);
    const tooltip = createTooltip(container);

    svg
      .append("g")
      .selectAll("path")
      .data(links)
      .join("path")
      .attr("d", (d) => taperedLinkPath(d, ky))
      .attr("fill", (d) => nodeColor(d.source.id))
      .attr("fill-opacity", 0.4)
      .attr("stroke", "none")
      .on("mouseenter", (event, d) => {
        d3.select(event.currentTarget).attr("fill-opacity", 0.65);
        tooltip.show(
          `<div style="font-weight:600">${d.source.label} → ${d.target.label}</div><div>${formatCell(d.cell)}${formatLinkPercentOfInflow(d)}</div>`,
          event
        );
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", (event) => {
        d3.select(event.currentTarget).attr("fill-opacity", 0.4);
        tooltip.hide();
      });

    const nodeGroup = svg.append("g").selectAll("g").data(nodes).join("g");

    nodeGroup
      .append("rect")
      .attr("x", (d) => d.x0)
      .attr("y", (d) => d.y0)
      .attr("width", (d) => d.x1 - d.x0)
      .attr("height", (d) => Math.max(1, d.y1 - d.y0))
      .attr("fill", (d) => nodeColor(d.id))
      .on("mouseenter", (event, d) => {
        tooltip.show(`<div style="font-weight:600">${d.label}</div><div>${formatCell(d.cell)}</div>`, event);
      })
      .on("mousemove", (event) => tooltip.move(event))
      .on("mouseleave", () => tooltip.hide());

    // Left-column nodes label to their left, right-column nodes label to
    // their right.
    nodeGroup.each(function (d) {
      const g = d3.select(this);
      const isLeft = INFLOW_BUCKET_KEYS.includes(d.id);
      const x = isLeft ? d.x0 - 10 : d.x1 + 10;
      const anchor = isLeft ? "end" : "start";
      const midY = (d.y0 + d.y1) / 2;
      g.append("text")
        .attr("x", x)
        .attr("y", midY - 6)
        .attr("text-anchor", anchor)
        .attr("font-size", NODE_LABEL_FONT_SIZE)
        .attr("fill", "var(--text-gray)")
        .text(d.label);
      g.append("text")
        .attr("x", x)
        .attr("y", midY + 10)
        .attr("text-anchor", anchor)
        .attr("font-size", NODE_COUNT_FONT_SIZE)
        .attr("font-weight", 700)
        .attr("fill", "var(--text-dark)")
        .text(formatCell(d.cell));
    });

    // The headline number: everyone who experienced homelessness this
    // period, centered above the gap between the two columns.
    const headline = svg.append("g").attr("class", "sankey-headline");
    const headlineCx = (leftX + rightX) / 2;
    headline
      .append("text")
      .attr("x", headlineCx)
      .attr("y", margin.top - 34)
      .attr("text-anchor", "middle")
      .attr("font-size", NODE_LABEL_FONT_SIZE)
      .attr("fill", "var(--text-gray)")
      .text(isFullYear ? `Experienced homelessness in ${periodLabel}` : `Experienced homelessness during ${periodLabel}`);
    headline
      .append("text")
      .attr("x", headlineCx)
      .attr("y", margin.top - 14)
      .attr("text-anchor", "middle")
      .attr("font-family", "var(--font-headline)")
      .attr("font-size", HEADLINE_LABEL_FONT_SIZE)
      .attr("font-weight", 700)
      .attr("fill", "var(--text-navy)")
      .text(formatCell(data.experiencedHomelessness));
  }, [data, periodLabel, isFullYear, populationSegment, width, height]);

  return <svg ref={svgRef} style={{ width: "100%", height: "auto" }} />;
}
