import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import KpiCard from "../KpiCard.jsx";
import FilterBar, { PopulationSegmentSelect } from "../FilterBar.jsx";
import FlowScrubberChart from "../charts/FlowScrubberChart.jsx";
import FlowScrubberControls from "../charts/FlowScrubberControls.jsx";
import useScrollJack from "../../hooks/useScrollJack.js";
import useMediaQuery from "../../hooks/useMediaQuery.js";
import { filterRows, distinctValues, resolveCell } from "../../lib/loadData.js";

const UNIT_SIZE = 20;
// Both side fields are purely decorative/symbolic (never tied 1:1 to real
// counts), so a fixed dense field works for any dataset size.
const FIELD_SIZE = 500;
// Rolling window: as more months of data accumulate over the years, this
// keeps the scrubber to a bounded, sittable-through length (the most
// recent 12 months) instead of growing indefinitely.
const ROLLING_MONTHS = 12;
const INFLOW_TYPES = ["newly_homeless", "return_from_housed", "return_from_inactive"];
const OUTFLOW_TYPES = ["permanently_housed", "inactive", "deceased"];

function formatMonthLabel(month) {
  const [year, m] = month.split("-");
  const date = new Date(Number(year), Number(m) - 1, 1);
  return date.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

// "up"/"down" if `current` is (or must be) higher/lower than `previous`;
// null if there's no previous month, or we genuinely can't tell.
//
// Suppression only ever hides a value below the threshold — a visible
// (marker-free) cell's true count is always at or above it (see
// suppression.py). So even without knowing a suppressed cell's exact hidden
// number, a visible current value is guaranteed higher than a suppressed
// previous one — "up" is safe there. The reverse (current suppressed) never
// needs handling here: KpiCard doesn't render an arrow next to a suppressed
// current value at all.
function trendDirectionFor(current, previous) {
  if (!previous || current.marker) return null;
  if (previous.marker) return "up";
  if (current.value > previous.value) return "up";
  if (current.value < previous.value) return "down";
  return null;
}

export default function OutflowSection({ flowRows }) {
  const [populationSegment, setPopulationSegment] = useState("all_population");
  const [activeIndex, setActiveIndex] = useState(0);
  const [direction, setDirection] = useState(null);
  // Independent of activeIndex/the scroll-jacked chart below: the KPI tiles
  // are a "latest snapshot, browse backward on demand" pattern, not a
  // chronological scrollytelling one, so they get their own month cursor
  // defaulted to the most recent month rather than following wherever the
  // chart's scroll-step happens to be.
  const [tileMonthIndex, setTileMonthIndex] = useState(0);
  const sectionRef = useRef(null);
  const isMobile = useMediaQuery("(max-width: 780px)");

  const scoped = useMemo(
    () => filterRows(flowRows, { populationSegment, dimension: "overall", category: "Overall" }),
    [flowRows, populationSegment]
  );
  const months = useMemo(() => distinctValues(scoped, "month").sort().slice(-ROLLING_MONTHS), [scoped]);

  const monthlySteps = useMemo(() => {
    const cellFor = (month, flow_type) => resolveCell(scoped.find((r) => r.month === month && r.flow_type === flow_type));
    return months.map((month) => ({
      month,
      activeTotal: cellFor(month, "active_total"),
      inflow: Object.fromEntries(INFLOW_TYPES.map((t) => [t, cellFor(month, t)])),
      outflow: Object.fromEntries(OUTFLOW_TYPES.map((t) => [t, cellFor(month, t)])),
    }));
  }, [months, scoped]);

  useEffect(() => {
    setActiveIndex(0);
    setDirection(null);
  }, [populationSegment]);

  // Every month dashboard_flow_monthly.json carries is already a completed
  // month (the pipeline's export window excludes the current in-progress
  // one), so the last entry in `months` is exactly "the most recent full
  // month" — no extra filtering needed, just point the tile cursor at it
  // whenever the available month list changes (new population segment, or
  // data finishes loading).
  useEffect(() => {
    setTileMonthIndex(monthlySteps.length - 1);
  }, [populationSegment, monthlySteps.length]);

  const onStep = useCallback((delta) => {
    setActiveIndex((i) => Math.min(monthlySteps.length - 1, Math.max(0, i + delta)));
    setDirection(delta > 0 ? "forward" : "backward");
  }, [monthlySteps.length]);

  const onScrub = useCallback(
    (i) => {
      setDirection(i > activeIndex ? "forward" : "backward");
      setActiveIndex(i);
    },
    [activeIndex]
  );

  const { isPinned } = useScrollJack({
    sectionRef,
    activeIndex,
    minIndex: 0,
    maxIndex: monthlySteps.length - 1,
    onStep,
    // Deliberately much shorter than FLIGHT_MS (7s): the chart interrupts
    // and restarts cleanly when a new step arrives mid-flight (see its
    // `.interrupt()` calls), so the cooldown only needs to pace scroll
    // *input*, not wait out the full animation. Gating it to the animation
    // length forced a ~6s wait between steps, which made any normal-paced
    // scroll look like repeated impatient attempts and kick the section's
    // scroll trap after only one or two steps.
    cooldownMs: 900,
    enabled: !isMobile && monthlySteps.length > 1,
  });

  if (!monthlySteps.length) {
    return (
      <section className="section">
        <h2 className="section-heading">Entries, Active Caseload &amp; Exits</h2>
        <p className="section-subhead">
          How many people are entering, staying active in, and leaving our homelessness response system each month?
          Scroll to step through the last {ROLLING_MONTHS} months.
        </p>
        <FilterBar>
          <PopulationSegmentSelect value={populationSegment} onChange={setPopulationSegment} />
        </FilterBar>
        <p className="suppressed-note">No data available for this population.</p>
      </section>
    );
  }

  const current = monthlySteps[activeIndex];
  // Clamped defensively: tileMonthIndex is reset to point at the latest
  // month whenever monthlySteps.length changes (see effect above), but that
  // reset fires in an effect *after* render, so the render that first sees
  // a shorter monthlySteps array (e.g. right after a population-segment
  // change) could otherwise read past the end of it for one frame.
  const clampedTileIndex = Math.min(tileMonthIndex, monthlySteps.length - 1);
  const tileCurrent = monthlySteps[clampedTileIndex];
  // undefined at the oldest month in the window — trendDirectionFor treats
  // that the same as "no prior data", so cards just show no arrow there.
  const tilePrevious = monthlySteps[clampedTileIndex - 1];

  return (
    <section className="section flow-scrubber-section">
      <h2 className="section-heading">Entries, Active Caseload &amp; Exits</h2>
      <p className="section-subhead">
        How many people are entering, staying active in, and leaving our homelessness response system each month?
        Scroll to step through the last {ROLLING_MONTHS} months.
      </p>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={setPopulationSegment} />
      </FilterBar>
      <div className="kpi-row-month">
        <span>{formatMonthLabel(tileCurrent.month)}</span>
        <div className="kpi-month-nav">
          <button
            type="button"
            aria-label="Show an older month"
            disabled={tileMonthIndex <= 0}
            onClick={() => setTileMonthIndex((i) => Math.max(0, i - 1))}
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Show a more recent month"
            disabled={tileMonthIndex >= monthlySteps.length - 1}
            onClick={() => setTileMonthIndex((i) => Math.min(monthlySteps.length - 1, i + 1))}
          >
            ›
          </button>
        </div>
      </div>
      <div className="kpi-rows">
        <div className="kpi-row kpi-row-hero">
          <KpiCard
            label="Actively Homeless"
            value={tileCurrent.activeTotal.value?.toLocaleString()}
            marker={tileCurrent.activeTotal.marker}
            trendDirection={trendDirectionFor(tileCurrent.activeTotal, tilePrevious?.activeTotal)}
            goodDirection="down"
          />
        </div>
        <div className="kpi-row">
          <KpiCard
            label="Newly Homeless"
            value={tileCurrent.inflow.newly_homeless.value?.toLocaleString()}
            marker={tileCurrent.inflow.newly_homeless.marker}
            trendDirection={trendDirectionFor(tileCurrent.inflow.newly_homeless, tilePrevious?.inflow.newly_homeless)}
            goodDirection="down"
          />
          <KpiCard
            label="Return from Housed"
            value={tileCurrent.inflow.return_from_housed.value?.toLocaleString()}
            marker={tileCurrent.inflow.return_from_housed.marker}
            trendDirection={trendDirectionFor(tileCurrent.inflow.return_from_housed, tilePrevious?.inflow.return_from_housed)}
            goodDirection="down"
          />
          <KpiCard
            label="Return from Inactive"
            value={tileCurrent.inflow.return_from_inactive.value?.toLocaleString()}
            marker={tileCurrent.inflow.return_from_inactive.marker}
            trendDirection={trendDirectionFor(tileCurrent.inflow.return_from_inactive, tilePrevious?.inflow.return_from_inactive)}
            goodDirection="down"
          />
        </div>
        <div className="kpi-row">
          <KpiCard
            label="Inactive"
            value={tileCurrent.outflow.inactive.value?.toLocaleString()}
            marker={tileCurrent.outflow.inactive.marker}
            trendDirection={trendDirectionFor(tileCurrent.outflow.inactive, tilePrevious?.outflow.inactive)}
            goodDirection={null}
          />
          <KpiCard
            label="Permanently Housed"
            value={tileCurrent.outflow.permanently_housed.value?.toLocaleString()}
            marker={tileCurrent.outflow.permanently_housed.marker}
            trendDirection={trendDirectionFor(tileCurrent.outflow.permanently_housed, tilePrevious?.outflow.permanently_housed)}
            goodDirection="up"
          />
          <KpiCard
            label="Deceased"
            value={tileCurrent.outflow.deceased.value?.toLocaleString()}
            marker={tileCurrent.outflow.deceased.marker}
            trendDirection={trendDirectionFor(tileCurrent.outflow.deceased, tilePrevious?.outflow.deceased)}
            goodDirection={null}
          />
        </div>
      </div>
      {isMobile ? (
        <>
          <p className="flow-scrubber-month">{formatMonthLabel(current.month)}</p>
          <FlowScrubberControls
            monthlySteps={monthlySteps}
            activeIndex={activeIndex}
            unitSize={UNIT_SIZE}
            fieldSize={FIELD_SIZE}
            onChange={onScrub}
          />
          <p className="suppressed-note">Center circle: 1 dot ≈ {UNIT_SIZE} people</p>
        </>
      ) : (
        <div className="flow-scrubber-wrap" ref={sectionRef}>
          <div className={`flow-scrubber-sticky${isPinned ? " is-pinned" : ""}`}>
            {/* Lives inside the pinned box (not above it) so it stays on
                screen while the section is pinned and animating. */}
            <p className="flow-scrubber-month">{formatMonthLabel(current.month)}</p>
            <FlowScrubberChart
              monthlySteps={monthlySteps}
              activeIndex={activeIndex}
              direction={direction}
              unitSize={UNIT_SIZE}
              fieldSize={FIELD_SIZE}
            />
            <p className="suppressed-note">Center circle: 1 dot ≈ {UNIT_SIZE} people</p>
            {isPinned && monthlySteps.length > 1 && (
              <p className="flow-scrubber-hint">Scroll to step through months</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
