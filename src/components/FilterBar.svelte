<script>
  export let filters = []; // [{ key, label }]
  export let rows = [];     // unfiltered dataset, to derive dropdown options
  export let selections;   // bound object: { [key]: value }

  function optionsFor(key) {
    return Array.from(new Set(rows.map((r) => r[key]))).sort();
  }
</script>

{#if filters.length > 0}
  <div class="filter-bar">
    {#each filters as f (f.key)}
      <label>
        <span>{f.label}</span>
        <select bind:value={selections[f.key]}>
          <option value="All">All</option>
          {#each optionsFor(f.key) as opt}
            <option value={opt}>{opt}</option>
          {/each}
        </select>
      </label>
    {/each}
  </div>
{/if}

<style>
  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-family: var(--font-body);
    font-size: var(--type-scale-caption);
    color: var(--color-ink-soft);
  }

  select {
    font-family: var(--font-body);
    font-size: 0.9375rem;
    color: var(--color-ink);
    background: var(--color-paper-raised);
    border: 1px solid var(--color-line);
    border-radius: 4px;
    padding: 0.4rem 0.6rem;
    min-width: 160px;
  }

  select:focus-visible {
    outline: 2px solid var(--color-flow-primary);
    outline-offset: 1px;
  }
</style>
