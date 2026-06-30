<script>
  import { onMount } from 'svelte';
  import * as d3 from 'd3';

  export let data; // [{ category, value }]

  let container;
  let width = 800;
  const barHeight = 36;
  const barGap = 12;
  const labelWidth = 220;

  function render() {
    if (!container || !data) return;
    container.innerHTML = '';

    const height = data.length * (barHeight + barGap) + barGap;
    const maxValue = d3.max(data, (d) => d.value) || 1;
    const scale = d3.scaleLinear().domain([0, maxValue]).range([0, width - labelWidth - 60]);

    const svg = d3.select(container)
      .append('svg')
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('width', '100%')
      .attr('height', height)
      .attr('role', 'img')
      .attr('aria-label', 'Bar chart');

    const row = svg.append('g')
      .selectAll('g')
      .data(data)
      .join('g')
      .attr('transform', (_, i) => `translate(0, ${barGap + i * (barHeight + barGap)})`);

    row.append('text')
      .attr('x', labelWidth - 12)
      .attr('y', barHeight / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', 'end')
      .attr('font-family', 'var(--font-body)')
      .attr('font-size', '13px')
      .attr('fill', 'var(--color-ink)')
      .text((d) => d.category);

    row.append('rect')
      .attr('x', labelWidth)
      .attr('y', 0)
      .attr('height', barHeight)
      .attr('width', (d) => scale(d.value))
      .attr('fill', 'var(--color-flow-primary)');

    row.append('text')
      .attr('x', (d) => labelWidth + scale(d.value) + 8)
      .attr('y', barHeight / 2)
      .attr('dy', '0.35em')
      .attr('font-family', 'var(--font-body)')
      .attr('font-size', '13px')
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

<div class="bar-wrap" bind:this={container}></div>

<style>
  .bar-wrap {
    width: 100%;
    overflow-x: auto;
  }
</style>
