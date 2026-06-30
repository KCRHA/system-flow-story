<script>
  import { onMount } from 'svelte';
  import SankeyDiagram from './components/SankeyDiagram.svelte';
  import flowData from '../data/flow_sample.json';

  let rootEl;

  // Tell the parent page (if we're embedded in an iframe) how tall we are,
  // so the host site can size the iframe instead of showing a scrollbar.
  // Pair this with the embed-helper.js snippet in README.md on the host page.
  function postHeight() {
    if (window.parent === window) return; // not embedded
    const height = rootEl.scrollHeight;
    window.parent.postMessage({ kcrhaEmbedHeight: height }, '*');
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
    <p class="eyebrow">System Flow &middot; {flowData.as_of}</p>
    <h1>How People Move Through King County's Homelessness Response System</h1>
    <p class="dek">
      Every year, thousands of people enter the region's homelessness response
      system through outreach and coordinated entry. What happens next — and
      how long it takes — varies widely depending on the path someone takes.
      This is a look at where people go, and where the system holds them longest.
    </p>
  </header>

  <section class="diagram-section">
    <h2>The path from entry to exit</h2>
    <p class="caption">
      Width of each band reflects the number of people moving along that path.
      Hover any segment for exact counts.
      <!-- TODO: replace placeholder figures in data/flow_sample.json with your
           quarterly CE/HMIS aggregate export before publishing. -->
    </p>
    <SankeyDiagram data={flowData} />
    <p class="source-note">
      Source: KCRHA Coordinated Entry &amp; HMIS data, {flowData.as_of}. Figures
      shown are placeholder values — replace before publishing.
    </p>
  </section>

  <section class="narrative">
    <h2>What this tells us</h2>
    <p>
      <!-- TODO: this is where your reporting/analysis goes — what's the story
           in this data? Where's the bottleneck? What changed this quarter? -->
      Add 2–3 paragraphs of plain-language narrative here, the same way a Times
      data story walks a reader through what the chart means before moving on
      to the next one.
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
    margin-bottom: var(--space-5);
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

  .diagram-section {
    border-top: 1px solid var(--color-line);
    border-bottom: 1px solid var(--color-line);
    padding: var(--space-4) 0;
    margin-bottom: var(--space-5);
  }

  h2 {
    font-size: var(--type-scale-h2);
    margin-bottom: var(--space-2);
  }

  .caption {
    color: var(--color-ink-soft);
    font-size: var(--type-scale-caption);
    max-width: 56ch;
    margin-bottom: var(--space-3);
  }

  .source-note {
    font-size: var(--type-scale-caption);
    color: var(--color-ink-soft);
    margin-top: var(--space-2);
  }

  .narrative p {
    max-width: 64ch;
  }
</style>
