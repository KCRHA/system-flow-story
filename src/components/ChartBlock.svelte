<script>
  import { loadDataset } from '../lib/loadData.js';
  import { filterRows } from '../lib/filterData.js';
  import { toSankey } from '../lib/reshapers/toSankey.js';
  import { toBarChart } from '../lib/reshapers/toBarChart.js';
  import FilterBar from './FilterBar.svelte';
  import SankeyChart from './charts/SankeyChart.svelte';
  import BarChart from './charts/BarChart.svelte';

  // Add new chart types here: map a type name to its reshaper + component.
  const CHART_TYPES = {
    sankey: { reshape: (rows, cfg) => toSankey(rows, cfg.labels || {}), component: SankeyChart },
    bar: { reshape: (rows) => toBarChart(rows), component: BarChart }
  };

  export let config; // one entry from charts.config.js

  let rawRows = [];
  let loadError = null;
  let selections = Object.fromEntries((config.filters || []).map((f) => [f.key, 'All']));

  $: chartType = CHART_TYPES[config.type];
  $: filteredRows = filterRows(rawRows, selections);
  $: chartData = rawRows.length ? chartType.reshape(filteredRows, config) : null;

  loadDataset(config.dataset)
    .then((rows) => { rawRows = rows; })
    .catch((err) => { loadError = err.message; });
</script>

<section class="chart-block" id={config.id}>
  <h2>{config.title}</h2>
  {#if config.caption}
    <p class="caption">{config.caption}</p>
  {/if}

  {#if loadError}
    <p class="error">Couldn't load this chart's data ({loadError}).</p>
  {:else if !rawRows.length}
    <p class="loading">Loading…</p>
  {:else}
    <FilterBar filters={config.filters || []} rows={rawRows} bind:selections />
    {#if filteredRows.length === 0}
      <p class="empty">No data matches the selected filters.</p>
    {:else}
      <svelte:component this={chartType.component} data={chartData} />
    {/if}
  {/if}
</section>

<style>
  .chart-block {
    border-top: 1px solid var(--color-line);
    padding: var(--space-4) 0;
  }

  h2 {
    font-size: var(--type-scale-h2);
    margin-bottom: var(--space-1);
  }

  .caption {
    color: var(--color-ink-soft);
    font-size: var(--type-scale-caption);
    max-width: 56ch;
    margin-bottom: var(--space-3);
  }

  .loading,
  .error,
  .empty {
    color: var(--color-ink-soft);
    font-size: var(--type-scale-caption);
  }

  .error {
    color: #9a3b3b;
  }
</style>
