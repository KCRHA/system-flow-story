# KCRHA System Flow Dashboard

A scrollytelling dashboard about homelessness system flow in King County —
inflow, resource access, length of time homeless, resolution/outflow, and
system capacity — built as a static React/Vite/D3/Scrollama site, mounted
directly into the main KCRHA site's own page via a Shadow DOM embed script
(not an iframe — see "Embedding on the KCRHA website" below).

The frontend never talks to a database directly. It only reads static
JSON files in `public/data/`, refreshed on a schedule by the pipeline in
`pipeline/`. This keeps the publicly-hosted site from ever exposing raw
person-level data, and keeps small-cell suppression enforceable at build
time in one place.

## Data contract

### `dashboard_flow_monthly.json`

One row per `(month, population_segment, dimension, category, flow_type)`.

| column | notes |
|---|---|
| `month` | first of month |
| `population_segment` | `all_population`, `yya`, `chronic`, `single_adults`, `veterans`, `family` — segments are allowed to overlap (e.g. a chronic veteran, or a YYA household that's also a family); each is its own independent filter over the same people, not a mutually-exclusive bucket |
| `dimension` | `overall` · `race_aian`, `race_asian`, `race_black`, `race_nhpi`, `race_white`, `race_hl`, `race_mena`, `race_multiracial` · `gender_identity`, `gender_alignment` · `household_type` · `age_category` — see below |
| `category` | value within that dimension; `Overall` when `dimension = overall` |
| `flow_type` | see enum below |
| `inflow_bucket` / `outflow_bucket` | only present on `indiv_flow_*` rows (see below) — the two bucket keys that flow_type encodes, broken into their own columns so the suppression pipeline can group "every cell sharing this row" / "every cell sharing this column" without parsing the flow_type string |
| `count` | **null when `suppression_marker` is set** |
| `suppression_marker` | `null` (not suppressed), `"*"` (primary — this cell's own count fell below 11), `"**"` (secondary/complementary — suppressed to prevent a `"*"` neighbor in the same group from being recovered by arithmetic), or `"insufficient_population"` (this whole (month, population_segment, dimension, category) scope was blanked because the group had nothing left to hide a suppressed cell behind — see Suppression, below) |

The 8 `race_*` dimensions are each their own independent binary dimension (`Included` / `Not Included`), not 8 categories of one `race_ethnicity` dimension — a person can be `Included` in more than one at once (e.g. Black AND Hispanic/Latina/o), which a single overlapping dimension can't represent cleanly. The frontend's "Race / Ethnicity" filter is a virtual demographic type layered on top of these 8 (see `App.jsx`'s `RACE_ETHNICITY_CATEGORY_DIMENSIONS`), not a dimension that exists in the exported data itself. `age_category` isn't offered as a frontend filter for the `yya` population segment — everyone there already falls in the same one or two age tiers by definition.

`household_type` and `age_category` are episode-scoped (a person's household composition, or age tier at episode start, can differ between two of their own episodes), unlike the other dimensions, which are person-level constants from `client_demographics`. That distinction matters for one thing: the `indiv_*`/`indiv_flow_*` flow_types below (which rely on a single static category per person) are never broken out by these two dimensions — they're only ever emitted under `overall` and the remaining (person-level) dimensions.

`flow_type` values:
- **Inflow** (per-episode events): `newly_homeless`, `return_from_housed`, `return_from_inactive`
- **Outflow** (per-episode events): `permanently_housed`, `inactive`, `deceased`
- **Active / status**: `active_total`, `unsheltered`, `sheltered`, `temporarily_housed`, `active_ce_engaged`, `active_not_ce_engaged`
- **Resource access**: `resource_{type}_engaged` / `_newly_enrolled` / `_exited` for `type` in `outreach`, `emergency_shelter`, `transitional_housing`, `rapid_rehousing`, `psh`, `prevention`
- **Distinct-person total**: `experienced_homelessness` — everyone who touched the system at all that month, including someone who arrived and exited within the same month (unlike `active_total`, which is "active as of month end")
- **Individual partition** (`indiv_*`): every person who experienced homelessness that month is assigned to exactly one inflow bucket and exactly one outflow bucket — `indiv_already_active`, `indiv_newly_homeless`, `indiv_return_from_housed`, `indiv_return_from_inactive` (inflow buckets, sum to `experienced_homelessness`) and `indiv_still_active`, `indiv_aged_out`, `indiv_permanently_housed`, `indiv_inactive`, `indiv_deceased` (outflow buckets, also sum to `experienced_homelessness`). Unlike the per-episode inflow/outflow counts above (which the same person can contribute to more than once in a month), this is a true one-bucket-per-person partition — built for the sankey and KPI cards, which represent individuals, not episodes. `indiv_aged_out` is always 0 outside the `yya` segment; it captures someone dropping out of YYA tracking mid-episode with no HMIS inflow/outflow event of its own.
- **Individual cross-tab** (`indiv_flow_{inflow_bucket}_to_{outflow_bucket}`): the per-person pairing of the two buckets above (all 4 × 5 = 20 combinations) — e.g. "of the people newly homeless this month, how many were still active vs. permanently housed by month's end." Powers the sankey's actual links. These rows also carry `inflow_bucket`/`outflow_bucket` columns (see the table above).

### `dashboard_flow_yearly.json` / `dashboard_flow_quarterly.json`

Same shape as `dashboard_flow_monthly.json` (`year`/`quarter` in place of `month`; `quarter` is that quarter's start date, e.g. Q3 2026 → `2026-07-01`, matching `dashboard_return_cohorts`' `exit_quarter` convention), but carrying only `experienced_homelessness` and the `indiv_*`/`indiv_flow_*` rows — not the per-episode inflow/outflow/active/resource-access flow_types, which the frontend already gets from summing `dashboard_flow_monthly` client-side where that's valid.

These exist because `experienced_homelessness` and the `indiv_*`/`indiv_flow_*` partition **can't** be reconstructed by summing monthly cells: a person with more than one distinct episode in the same year (newly homeless in February, exits to housing, returns from housed in October) would be double-counted if each month's partition were just added together. Both builders instead union/partition over the whole period's episodes at once, the same way the monthly builder does for a single month. `dashboard_flow_quarterly.json` powers `OutflowSection`'s quarter-drill-down pills; a quarter whose three calendar months aren't all complete is omitted entirely rather than emitted as a partial quarter.

### `dashboard_length_monthly.json`

One row per `(month, population_segment, dimension, category)` — length-of-time-homeless distribution stats among people active that month: `n`, `median_days`, `p25_days`, `p75_days`, `mean_days`, `suppression_marker` (based on `n < 11`). All five numeric fields are nulled together when `suppression_marker` is set — the distribution stats are just as revealing as `n` itself for a small group, so they can't be left populated next to a suppressed count.

### `dashboard_return_cohorts.json`

One row per `(exit_quarter, population_segment, dimension, category)`. A permanently-housed episode outflow starts the clock; "returned" means the same person has a new homeless episode within **182 days** (a single 6-month window — chosen as the most reportable-and-accurate horizon for this dashboard's purpose, not the `Return from Housed` inflow definition's broader 730-day gap threshold used upstream in episode_systemwide; see `RETURN_WINDOW_DAYS` in `pipeline/config.py`). Quarterly, not monthly — `exit_quarter` is the quarter's start date; `window_complete` is anchored to it the same way the old monthly version anchored to month start.

| column | notes |
|---|---|
| `n_exited` | cohort size (denominator); `suppression_marker` set if <11 |
| `n_returned` | how many returned within the window; null when `suppression_marker` is set |
| `pct_returned` | null if suppressed *or* if `window_complete = false` |
| `window_complete` | false for exit quarters less than 6 months old — those cohorts haven't had time to fully mature, so their return rate isn't yet accurate. The frontend excludes these entirely rather than showing a partial/misleading rate; the chart only ever shows the most recent 8 quarters (2 years) that *are* complete. |

The chart itself (`ReturnCohortChart.jsx`) is a stacked bar per exit quarter: total bar height is `n_exited`, split into a "returned" segment (`n_returned`) and a "remained housed" segment (`n_exited - n_returned`), each labeled with its percent share — so the exit volume, the split, and the exact rate are all visible in one bar.

### `dashboard_capacity_monthly.json`

One row per `(month, project_type)`, `project_type` in `ph`, `th`, `es`, `rrh`. **Not suppressed** — this is aggregate program inventory data, not person-level counts.

| column | notes |
|---|---|
| `units_in_system` | household capacity — the default measure throughout this dashboard |
| `throughput_hh_per_unit` | households enrolled per unit in the period |
| `pct_utilization` | unit-nights used / unit-nights available |
| `beds_in_system` | individual-person capacity — a secondary reference figure only; not interchangeable with units |

### `dashboard_capacity_quarterly.json`

One row per `(quarter, project_type)`, feeding the Utilization chart's trailing 3-year (12-quarter) trend. **Not suppressed**, same rationale as the monthly table above. Same columns as `dashboard_capacity_monthly.json`, sourced from `program_performance_metrics`'s own `TimePeriod = 'Quarter'` rows rather than summed from the `'Month'` rows above — `UnitNightsUsed`/`AvailableDenominator` are per-night counts with no double-counting risk from summing either way, but the source's native quarterly rows are used for consistency with the yearly Turnover table.

Both this table and the monthly one only include periods where `TimePeriodEndDate < as_of` (today, at export time) — filtered on each row's own end date, not the export window's start/end cutoff. That window cutoff is scoped by `TimePeriodStartDate` at monthly granularity, so it correctly excludes the current in-progress *month*, but doesn't generalize to longer grains: a quarter/year "starting" within the safe window can still extend well past today (confirmed this let an in-progress quarter — units_in_system etc. only reflecting its first month so far — into the export). Yearly deliberately does *not* get this filter — the current year is intentionally included there, labeled "year to date" by the frontend's Year selector.

### `dashboard_capacity_yearly.json`

One row per `(year, project_type)`, feeding the Turnover chart's percent-exited and households-per-unit metrics. **Not suppressed**, same rationale as the monthly table above.

Sourced from `program_performance_metrics`'s own `TimePeriod = 'Year'` rows — deliberately *not* derived by summing the `'Month'` rows the table above uses. `EnrolledDuringTimeframe`/`ExitedDuringTimeframe` are monthly snapshots (a household enrolled across a multi-month stay is counted again in every month of it), so summing them would overcount relative to a true annual headcount; the source table's own Year-grain rows are already a correctly deduplicated once-per-household-per-year count.

| column | notes |
|---|---|
| `enrolled` / `exited` / `active` | raw annual counts, for reference. `enrolled` (`EnrolledDuringTimeframe`) runs lower than `active` (`ActiveEnrollmentsInTimeframe`) and isn't used to derive either metric below — confirmed `active = exited + ActiveAtEndOfTimeframe` (holds for 5369/5372 program-years checked), i.e. `active` is the true "touched this project at any point in the year" headcount, while `enrolled` is some narrower count (e.g. new enrollments only) that let `pct_exited` exceed 100% when used as the denominator |
| `pct_exited` | `exited / active` — share of everyone active at any point that year who also exited within it (vs. still active at year-end). Structurally bounded to `[0, 1]`; null if `active = 0` |
| `households_per_unit` | `active / units_in_system` — e.g. one Emergency Shelter unit with ~2-month average stays reads as ~6/year; null if `units_in_system = 0` |

## Suppression (`pipeline/suppression.py`)

Applied at pipeline build time, never in the frontend. Suppressed counts are
**never published, not even rounded** — a reader sees a marker instead of a
number, and that marker is the whole protection; there's nothing rounding
would additionally guard against here.

1. **Primary threshold** — any *nonzero* cell with count under
   `SUPPRESSION_THRESHOLD` (11, HUD convention) is nulled and marked `"*"`.
   A true zero is never suppressed: it can't identify any specific person,
   so there's nothing to protect by hiding it — anytime the real count is 0,
   it's shown as 0.
2. **Secondary (complementary) suppression** — an otherwise-visible cell in
   the same group is additionally nulled and marked `"**"` whenever:
   - **exactly one** category in the group is primary-suppressed (its value
     could be recovered by subtracting every visible category from a known
     group total), **or**
   - **two or more** categories are primary-suppressed and they all share
     the *exact same* true count, and that count is **1** or **10** — the
     two values where the suppression range itself (any nonzero count up to
     `SUPPRESSION_THRESHOLD - 1`, zero being exempt per above) forces every
     suppressed cell in the group to an identical, guessable number even
     without a group total: all-1s is the minimum possible cell, all-10s is
     the maximum possible cell still under the threshold. Two or more
     suppressed cells with *different* true values are safe as-is — many
     splits of an unknown sum are possible, so no single value is forced.

   The `"**"` mark lands on the next-smallest currently-visible category in
   the group, never on a category that's already `"*"` — and prefers a
   nonzero category over a zero one, since hiding a zero protects the
   suppressed cell just as well arithmetically but there's no privacy
   reason to ever hide one; a zero is only picked if it's the only visible
   category left.
3. **Cross-tab secondary suppression** (`apply_crosstab_secondary_suppression`)
   — the `indiv_flow_*` cross-tab cells (see the flow_type enum above) aren't
   a dimension/category breakdown, so pass 2's grouping never sees them as
   siblings of each other. But every cell sharing an `inflow_bucket` ("row")
   sums to that bucket's own published `indiv_*` total, and same for every
   cell sharing an `outflow_bucket` ("column") — the same sibling-group risk
   as rule 2 above, just keyed by `inflow_bucket`/`outflow_bucket` instead of
   `dimension`/`category`. Resolves both axes jointly within each period
   (not as two independent passes), so a rare category claimed as one row's
   secondary pick doesn't leave its own column with nothing left to hide
   behind.
4. **Race cross-dimension suppression** (`apply_race_crossdim_suppression`)
   — the 8 `race_*` dimensions are deliberately not mutually exclusive (see
   the data contract above), so two individually-safe, above-threshold
   "Included" counts from two different race dimensions, plus the scope's
   own published `overall` total, can jointly lower-bound the population
   Included in *both* via inclusion-exclusion (`count_A + count_B - total`)
   — a number nobody decided to publish, which can land under the
   suppression threshold even though every contributing cell looks safe on
   its own. When that happens, both categories of one of the two violating
   dimensions are suppressed together for that scope (suppressing only the
   `Included` cell would hand the value right back via its own `Not
   Included` sibling and the known total).
5. **Insufficient-population fallback** (`apply_insufficient_population_fallback`)
   — a small population segment crossed with a low-cardinality dimension
   (e.g. `gender_alignment`'s 3 categories) can leave a group needing
   secondary suppression with no visible sibling cell left to hide behind at
   all. There's no partial fix for that, so instead of one more cell, the
   *entire* `(month, population_segment, dimension, category)` scope —
   every flow_type in it, not just the one that triggered the check — is
   blanked together and marked `"insufficient_population"`. The frontend
   shows a dedicated "population too small to display" message for this
   marker rather than routing it through the ordinary `"*"`/`"**"` display.
6. **Validation gate** (`suppression.validate()` / `validate_crosstab()`) —
   the pipeline exits non-zero if any exported row needed secondary
   suppression but didn't get it, or has a marker with a non-null count.
   This is a hard gate: the exported JSON is publicly fetchable and
   permanent once committed (a later commit can't erase what an earlier one
   exposed via git history), so a violation must fail the build, not just
   log a warning.

**Frontend rendering**: a suppressed cell always shows its marker (`*` or
`**`) in place of the number — never 0, never blank. 0 is a real, reportable
value; a marker means "we withheld this number." The sankey (`FlowSankeyChart.jsx`)
renders this visually too: at a given node, whichever suppressed links are
doing the "protecting" (secondary links, or primary links when that node has
no secondary link of its own) expand to fill whatever's left of the node's
true total, while any other suppressed links at that node stay a small fixed
sliver — so a visual gap never reappears just because a particular node's
protection happened to come from primary suppression alone.

## Pipeline (`pipeline/`)

Sourced from Azure Synapse (`rha-bnl-prod.sql.azuresynapse.net` / `rhabnl`) via `team_custom_modules.remote_connections.RemoteDataConn` (from [DataHubDevelopment](https://github.com/KCRHA/DataHubDevelopment)) — Entra ID auth, no passwords in code.

- `config.py` — thresholds, population-segment/dimension enums, the rolling export window (last 5 completed calendar years + completed months of the current year, recomputed every run), the HUD `ProjectTypeCode` → `ph`/`th`/`es`/`rrh` rollup.
- `connection.py` — thin wrapper around `team_custom_modules.remote_connections.RemoteDataConn` for Synapse access, so pipeline scripts never import the vendored module directly.
- `demographics.py` — derives the person-level `race_*`/`gender_identity`/`gender_alignment` rollup columns from `client_demographic`'s raw multi-select flags (`RaceAndEthnicity_*`, `GenderExpanded`), since none of those distinctions survive in the plain summary columns HMIS otherwise exposes.
- `population.py` — population-segment filters (`all_population`, `yya`, `chronic`, `single_adults`, `veterans`, `family`), ported from `BFZ_Monthly_Report`'s `filter_population()`; a separate enrollment-level variant covers the `resource_*` flow types below, since `all_program_enrollments` carries different column names for the same concepts.
- `build_flow.py` — `build_flow_rows`/`build_flow_yearly_rows`/`build_flow_quarterly_rows`, built from `episode_systemwide` + `episode_ce`, joined to `client_demographics`. Also builds the `indiv_*`/`indiv_flow_*` individual-partition rows that power the sankey and KPI cards.
- `build_length.py`, `build_return_cohorts.py` — same source tables as above.
- `build_flow.build_resource_access_rows()` (the `resource_*` flow types) — built from `all_program_enrollments` (one row per enrollment span, `ProjectStartDate`..`ProjectExitDate`, `ProjectTypeCode`), also joined to `client_demographics`. This table has no monthly grain of its own, so engaged/newly-enrolled/exited are derived by checking each month in the export window against every enrollment's date span.
- `build_capacity.py` — built from `program_performance_metrics` (`TimePeriod = 'Month'` / `'Quarter'` / `'Year'`) + `program_attributes`.
- `suppression.py` — see above.
- `export.py` — orchestrates the above and writes `public/data/dashboard_*.json`.

Every source table and column name above (`episode_systemwide`, `episode_ce`, `client_demographics`, `all_program_enrollments`, `program_performance_metrics`, `program_attributes`) was confirmed directly against the actual `DataHubDevelopment` notebook code, not the old methodology deck.

### Running the pipeline locally

```bash
az login                              # select the production subscription
python3 -m venv pipeline/.venv
source pipeline/.venv/bin/activate
pip install -r pipeline/requirements.txt
python3 -m pipeline.export
```

`pyodbc` also needs the Microsoft ODBC Driver for SQL Server installed at the
OS level (the Python package alone isn't enough) — a one-time install, before
the first run:

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18 mssql-tools18
```

Re-run `python3 -m pipeline.export` any time to refresh
`public/data/dashboard_*.json` from live Synapse data (`az login` again first
if your session has expired). In CI, `.github/workflows/sync-dashboard-data.yml`
runs the same export on a weekly schedule (or manual dispatch from the
Actions tab), authenticating via `AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`/`AZURE_TENANT_ID`
repo secrets instead of an interactive login.

## KPI direction indicators

Sourced from the KCRHA Five-Year Plan's "How We Measure Our Progress" table:

| metric | desired direction |
|---|---|
| Households exiting to permanent housing | ▲ increase |
| Households returning to homelessness after a PH exit | ▼ decrease |
| Units in the system | ▲ increase |
| Throughput | ▲ increase |
| Utilization | ▲ increase |

The Plan phrases the returns metric as 6/12/24-month windows; this dashboard applies the same direction to its single 182-day (6-month) `pct_returned` metric (see `dashboard_return_cohorts.json` above) rather than adding separate windows. An earlier iteration used a single 730-day (2-year) window instead — revisited in favor of 6 months, both for a shorter, more reportable-and-accurate horizon and because it lines up with the first of the Plan's three reference windows.

## Frontend

React + Vite + D3 (`d3-sankey` for the entries→active→exits alluvial) + Scrollama for scroll-triggered step transitions. Brand styling (`src/styles/tokens.css`) follows the KCRHA 2025 Brand Style Guide: Avenir Next LT Pro for headlines, Arial Nova for body text, and the approved priority-ordered charts & graphs palette.

The demographic filter (`FilterBar.jsx`) offers "All", "Race / Ethnicity", "Gender Identity", "Gender Alignment", and "Age Category" (`household_type` exists in the export but isn't offered as a filter). "Race / Ethnicity" is the one option that isn't a 1-to-1 stand-in for a single pipeline dimension — it's a virtual demographic type that maps the picked category label to the matching `race_*` dimension with `category = "Included"` (see `App.jsx`'s `RACE_ETHNICITY_CATEGORY_DIMENSIONS`), since there's no single overlap-free `race_ethnicity` dimension in the data. "Age Category" is hidden when the `yya` population segment is selected, since everyone there already falls in the same one or two age tiers.

```
npm install
npm run dev      # local dev server
npm run build    # production build to dist/
```

`public/data/*.json` currently contains **placeholder fixture data** (see `pipeline/` above for the real export) generated to match the exact table shapes documented here, so the frontend can be developed and reviewed before the pipeline has live Synapse access wired into CI.

## Embedding on the KCRHA website

`npm run build:embed` (config: `vite.embed.config.js`, entry: `src/embed.jsx`) builds a single self-contained script to `dist-embed/kcrha-system-flow-dashboard.js` — React/D3/Scrollama all bundled in, no dependency on anything the host page provides. It mounts into a **Shadow DOM** root on any `[data-kcrha-system-flow-dashboard]` element, not an iframe. See `embed-snippet.html` for the exact markup.

This isn't just a style choice — an iframe creates a separate browsing context with its own scroll, and this dashboard's core interactivity (`position: sticky` pinning, Scrollama's step transitions) only ever fires relative to the page's own top-level scroll. An iframe sized to fit its content exactly (the standard no-double-scrollbar trick) has *zero* internal scroll of its own, so none of that interactivity could ever trigger — everything would just render its first/default state and sit inert. Shadow DOM gives the same CSS isolation an iframe gives (styles can't leak either direction), without creating that separate scrolling context, so the dashboard's interactivity observes the real host page scroll directly.

One practical consequence: embedding now needs **template-level access**, not a CMS content-editor block — there's no iframe boundary to safely paste arbitrary host-supplied markup into anymore.

## Deploy

`.github/workflows/deploy.yml` builds and deploys `dist/` to GitHub Pages on every push to `main`. `.github/workflows/sync-dashboard-data.yml` refreshes `public/data/*.json` on a weekly schedule (or manual dispatch) and commits the result, which then triggers the deploy workflow.
