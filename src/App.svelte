<script>
  import { onMount } from 'svelte';
  import ChartBlock from './components/ChartBlock.svelte';
  import { chartConfigs } from './charts.config.js';

  let rootEl;

  function postHeight() {
    if (window.parent === window) return; // not embedded
    window.parent.postMessage({ kcrhaEmbedHeight: rootEl.scrollHeight }, '*');
  }

  onMount(() => {
    postHeight();
    const ro = new ResizeObserver(postHeight);
    ro.observe(rootEl);
    return () => ro.disconnect();
  });
</script>

<main bind:this={rootEl}>
  <header class="hero">
    <p class="eyebrow">System Flow</p>
    <h1>How People Move Through King County's Homelessness Response System</h1>
    <p class="dek">
      Every year, thousands of people enter the region's homelessness response
      system through outreach and coordinated entry. What happens next — and
      how long it takes — varies widely depending on the path someone takes.
      This is a look at where people go, and where the system holds them longest.
    </p>
  </header>

  {#each chartConfigs as config (config.id)}
    <ChartBlock {config} />
  {/each}

  <section class="narrative">
    <h2>What this tells us</h2>
    <p>
      <!-- TODO: your reporting/analysis goes here -->
      Add 2–3 paragraphs of plain-language narrative here, the same way a Times
      data story walks a reader through what the charts mean.
    </p>
  </section>
</main>

<style>
  main {
    max-width: 840px;
    margin: 0 auto;
    padding: var(--space-5) var(--space-3) var(--space-5);
  }

  .hero {
    margin-bottom: var(--space-4);
  }

  .eyebrow {
    font-family: var(--font-body);
    font-size: var(--type-scale-caption);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--color-flow-primary);
    margin: 0 0 var(--space-2);
  }

  h1 {
    font-size: var(--type-scale-hero);
    margin-bottom: var(--space-3);
  }

  .dek {
    font-family: var(--font-body);
    font-size: 1.1875rem;
    line-height: 1.6;
    color: var(--color-ink-soft);
    max-width: 62ch;
  }

  h2 {
    font-size: var(--type-scale-h2);
    margin-bottom: var(--space-2);
  }

  .narrative {
    padding-top: var(--space-4);
  }

  .narrative p {
    max-width: 64ch;
  }
</style>
