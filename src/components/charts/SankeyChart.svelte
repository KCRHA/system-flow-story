<script>
  import { onMount } from 'svelte';
  import * as d3 from 'd3';
  import { sankey, sankeyLinkHorizontal } from 'd3-sankey';

  export let data; // { nodes: [{id, label}], links: [{source, target, value}] }

  let container;
  let width = 800;
  const nodeWidth = 14;
  const nodePadding = 24;

  const colorFor = (id) => {
    if (id.startsWith('exit_housed')) return 'var(--color-flow-success)';
    if (id.startsWith('returned')) return 'var(--color-flow-muted)';
    return 'var(--color-flow-primary)';
  };

  function render() {
    if (!container || !data || data.nodes.length === 0) return;
    container.innerHTML = '';

    const height = Math.max(420, data.nodes.length * 46);

    const svg = d3.select(container)
      .append('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('width', '100%')
      .attr('height', height)
      .attr('role', 'img')
      .attr('aria-label', 'Sankey diagram showing how people move through the homelessness response system');

    const idIndex = new Map(data.nodes.map((d, i) => [d.id, i]));
    const sankeyNodes = data.nodes.map((d) => ({ ...d }));
    const sankeyLinks = data.links
      .filter((d) => idIndex.has(d.source) && idIndex.has(d.target))
      .map((d) => ({
        source: idIndex.get(d.source),
        target: idIndex.get(d.target),
        value: d.value
      }));

    const layout = sankey()
      .nodeId((_, i) => i)
      .nodeWidth(nodeWidth)
      .nodePadding(nodePadding)
      .extent([[1, 10], [width - 1, height - 10]]);

    const graph = layout({
      nodes: sankeyNodes.map((d) => ({ ...d })),
      links: sankeyLinks.map((d) => ({ ...d }))
    });

    svg.append('g')
      .attr('fill', 'none')
      .selectAll('path')
      .data(graph.links)
      .join('path')
      .attr('d', sankeyLinkHorizontal())
      .attr('stroke', (d) => colorFor(d.source.id))
      .attr('stroke-opacity', 0.28)
      .attr('stroke-width', (d) => Math.max(1, d.width))
      .append('title')
      .text((d) => `${d.source.label} \u2192 ${d.target.label}: ${d.value.toLocaleString()}`);

    const node = svg.append('g')
      .selectAll('g')
      .data(graph.nodes)
      .join('g');

    node.append('rect')
      .attr('x', (d) => d.x0)
      .attr('y', (d) => d.y0)
      .attr('height', (d) => d.y1 - d.y0)
      .attr('width', (d) => d.x1 - d.x0)
      .attr('fill', (d) => colorFor(d.id))
      .append('title')
      .text((d) => `${d.label}: ${d.value.toLocaleString()}`);

    node.append('text')
      .attr('x', (d) => (d.x0 < width / 2 ? d.x1 + 8 : d.x0 - 8))
      .attr('y', (d) => (d.y0 + d.y1) / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', (d) => (d.x0 < width / 2 ? 'start' : 'end'))
      .attr('font-family', 'var(--font-body)')
      .attr('font-size', '13px')
      .attr('fill', 'var(--color-ink)')
      .text((d) => d.label);

    node.append('text')
      .attr('x', (d) => (d.x0 < width / 2 ? d.x1 + 8 : d.x0 - 8))
      .attr('y', (d) => (d.y0 + d.y1) / 2)
      .attr('dy', '1.5em')
      .attr('text-anchor', (d) => (d.x0 < width / 2 ? 'start' : 'end'))
      .attr('font-family', 'var(--font-body)')
      .attr('font-size', '12px')
      .attr('fill', 'var(--color-ink-soft)')
      .text((d) => d.value.toLocaleString());
  }

  $: if (container && data) render();

  onMount(() => {
    const ro = new ResizeObserver((entries) => {
      width = entries[0].contentRect.width;
      render();
    });
    ro.observe(container);
    return () => ro.disconnect();
  });
</script>

<div class="sankey-wrap" bind:this={container}></div>

<style>
  .sankey-wrap {
    width: 100%;
    overflow-x: auto;
  }
</style>
