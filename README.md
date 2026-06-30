# KCRHA System Flow Story

A scrollable, NYT-style data story with multiple filterable charts, built as
a standalone static site and embedded on the main KCRHA website via iframe.

## Stack

- **Vite + Svelte** — app shell
- **D3 + d3-sankey** — chart rendering
- **GitHub Pages** — static hosting
- **GitHub Actions** — auto-builds and deploys on every push to `main`

## How charts work now (config-driven)

As of this version, charts are no longer hand-built one at a time. Adding
chart #11 means adding an entry to a config file — no new plumbing needed
unless it's a genuinely new chart *type*.

**The four pieces:**

1. **`public/data/*.json`** — your datasets, in "long format": one row per
   data point, tagged with whatever dimension columns you want to filter by
   (`region`, `quarter`, `program_type`, etc.), plus the value columns the
   chart type needs.

   - Sankey charts expect: `source_stage`, `target_stage`, `value`
   - Bar charts expect: `category`, `value`

2. **`src/charts.config.js`** — one entry per chart: which dataset, which
   chart type, which columns get filter dropdowns. This is the file you'll
   touch most.

3. **`src/lib/reshapers/`** — pure functions that turn filtered rows into
   whatever shape a chart type needs. `toSankey.js` and `toBarChart.js`
   exist now; add a new file here only when you need a genuinely new chart
   type (line, map, etc.).

4. **`src/components/charts/`** — the actual chart-drawing components
   (`SankeyChart.svelte`, `BarChart.svelte`). Each takes already-reshaped
   data as a prop and draws it with D3. Add a new component here alongside
   a new reshaper when you need a new chart type.

**Filtering** happens entirely in the browser: `ChartBlock.svelte` loads a
chart's full dataset once, then re-filters and re-reshapes it client-side
whenever someone changes a dropdown. No backend, no re-export needed per
filter combination — this is why datasets are "long format" rather than
pre-aggregated per view.

### Adding chart #11

1. Export a new long-format JSON to `public/data/your_dataset.json`
2. Add an entry to `chartConfigs` in `src/charts.config.js`
3. If it's a Sankey or bar chart, that's it — push and you're done
4. If it's a new chart type, add a reshaper in `src/lib/reshapers/` and a
   component in `src/components/charts/`, then register both in the
   `CHART_TYPES` map at the top of `ChartBlock.svelte`

## Local setup

```bash
npm install
npm run dev        # local dev server with hot reload
npm run build       # production build to /dist
npm run preview     # preview the production build locally
```

## First-time GitHub setup

1. Create a new **public** repo on GitHub (private repos need GitHub Pro/Team
   to use Pages — and either way, the published site is public once deployed).
2. Push this code to the `main` branch.
3. In the repo's **Settings → Pages**, set Source to **GitHub Actions**.
4. Confirm `base` in `vite.config.js` matches your repo name exactly.
5. Push to `main`. Check the **Actions** tab — your site goes live at
   `https://YOUR-ORG.github.io/YOUR-REPO/`.

## Quarterly data refresh workflow

1. Run your normal R/Python cleaning pipeline.
2. Export pre-aggregated, long-format JSON for each dataset that changed —
   matching the shape in `public/data/system_flow.json` or
   `exits_by_program.json` depending on chart type.
3. Watch your small cell sizes — this is public-facing. Apply whatever
   suppression threshold you'd normally use for public KCRHA reporting.
4. Replace the relevant file(s) in `public/data/`, commit, push to `main`.
5. GitHub Actions rebuilds and redeploys automatically.

## Embedding on the KCRHA website

See `embed-snippet.html` for the iframe + auto-resize script to paste into
the host page. The app posts its height to the parent window on load and
resize, so the iframe sizes itself rather than showing a scrollbar — this
works regardless of CMS, since it's just an iframe.

Some platforms (Squarespace in particular) strip `<script>` tags from
embedded HTML blocks by default. If that's the case, fall back to a
fixed-height iframe.

## What's a placeholder right now

- `public/data/system_flow.json` and `exits_by_program.json` — fake numbers
  across a few regions/quarters, meant to demonstrate the filtering pattern.
  Replace with your real aggregates.
- The "What this tells us" narrative section in `App.svelte`
- `vite.config.js` base path — needs your real repo name
- `embed-snippet.html` — needs your real GitHub org/repo

## Design notes

Palette and type choices are in `src/lib/tokens.css` as CSS variables.
Color logic: slate-teal for steady-state pathways, warm clay reserved only
for the positive end state (exits to permanent housing), sage-grey for
returns/recurrence. Keep that restraint as you add charts — one color
doing one job each, not an arbitrary palette per chart.
