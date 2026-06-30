# KCRHA System Flow Story

A scrollable, NYT-style data story showing how people move through King
County's homelessness response system, built as a standalone static site
and embedded on the main KCRHA website via iframe.

**Assumption made:** "system flow" = a Sankey diagram of people moving
through stages of the homelessness response system (outreach → coordinated
entry → shelter/housing program → exit). If you meant something more like a
literal process/pipeline diagram (e.g. your data pipeline architecture)
rather than client flow through programs, let me know and the chart type
should change — a Sankey isn't the right shape for that.

## Stack

- **Vite + Svelte** — app shell, compiles to plain JS/CSS, no server needed
- **D3 + d3-sankey** — the flow diagram itself
- **GitHub Pages** — static hosting
- **GitHub Actions** — auto-builds and deploys on every push to `main`

## Local setup

```bash
npm install
npm run dev        # local dev server with hot reload
npm run build       # production build to /dist
npm run preview     # preview the production build locally
```

## First-time GitHub setup

1. Create a new **public** repo on GitHub (private repos need GitHub Pro/Team
   to use Pages — flagging this since this data will be public either way
   once published).
2. Push this code to the `main` branch.
3. In the repo's **Settings → Pages**, set Source to **GitHub Actions**.
4. Edit `vite.config.js` — set `base: '/your-repo-name/'` to match your
   actual repo name.
5. Push to `main`. The Actions tab will show the build/deploy running.
   Your site will be live at `https://YOUR-ORG.github.io/YOUR-REPO/`.

## Quarterly data refresh workflow

1. Run your normal R/Python cleaning pipeline.
2. Export a small, **pre-aggregated** JSON matching the shape in
   `data/flow_sample.json` (nodes + links with values). Do not export
   client-level rows — this repo is public.
3. Watch your small cell sizes — this is public-facing, so apply whatever
   suppression threshold you'd normally use for public KCRHA reporting.
4. Replace `data/flow_sample.json` (or point `App.svelte` at a new filename),
   commit, push to `main`.
5. GitHub Actions rebuilds and redeploys automatically — nothing else to do.

## Embedding on the KCRHA website

See `embed-snippet.html` for the iframe + auto-resize script to paste into
the host page. The Svelte app already posts its height to the parent window
on load and on resize (see `onMount` in `App.svelte`), so the iframe will
size itself to content rather than showing a scrollbar — this works
regardless of what CMS the main site runs on (WordPress, Squarespace,
custom), since it's just an iframe.

One thing to check once you know the CMS: some platforms (Squarespace in
particular) sanitize `<script>` tags out of embedded HTML blocks by default.
If that turns out to be the case, the fallback is a fixed-height iframe
(less elegant, but works everywhere) — let me know once you've confirmed
the platform and I can adjust.

## What's a placeholder right now

- `data/flow_sample.json` — fake numbers, swap with real aggregates
- The "What this tells us" narrative section in `App.svelte` — needs your
  actual analysis/reporting copy
- `vite.config.js` base path — needs your real repo name
- `embed-snippet.html` — needs your real GitHub org/repo in the iframe `src`

## Design notes

Palette and type choices are in `src/lib/tokens.css` as CSS variables —
change colors/fonts there rather than hunting through components. The
color logic is intentional: slate-teal for steady-state pathways, warm
clay reserved only for the positive end state (exits to permanent housing),
sage-grey for returns/recurrence. Keep that restraint if you extend the
palette — one accent color doing one job each.
