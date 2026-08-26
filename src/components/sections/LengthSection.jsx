import { useMemo, useState } from "react";
import Scrolly from "../Scrolly.jsx";
import LengthChart from "../charts/LengthChart.jsx";
import ReturnCohortChart from "../charts/ReturnCohortChart.jsx";
import FilterBar, { PopulationSegmentSelect } from "../FilterBar.jsx";
import { filterRows } from "../../lib/loadData.js";

export default function LengthSection({ lengthRows, returnCohortRows }) {
  const [populationSegment, setPopulationSegment] = useState("all_population");

  // Last 2 years only — full history is available but a shorter trailing
  // window keeps this legible.
  const scopedLength = useMemo(
    () =>
      filterRows(lengthRows, { populationSegment, dimension: "overall", category: "Overall" })
        .sort((a, b) => a.month.localeCompare(b.month))
        .slice(-24),
    [lengthRows, populationSegment]
  );
  // Only cohorts whose 6-month return window has fully elapsed have a
  // reportable rate at all (see window_complete in dashboard_return_cohorts.json)
  // — everything more recent is excluded rather than shown as a partial/
  // misleading rate. The most recent 8 of those complete quarters is what
  // actually renders, i.e. roughly the last 2 years, ending ~6 months ago.
  const scopedReturns = useMemo(
    () =>
      filterRows(returnCohortRows, { populationSegment, dimension: "overall", category: "Overall" })
        .filter((r) => r.window_complete)
        .sort((a, b) => a.exit_quarter.localeCompare(b.exit_quarter))
        .slice(-8),
    [returnCohortRows, populationSegment]
  );

  const steps = [
    "Among people active in the system each month, how long have they been experiencing homelessness so far — and is that changing over time? The line shows the median; the shaded band shows where the middle 50% of people fall.",
    "A related question: of the people who exit to permanent housing, how many return to homelessness within six months? Shown here are the last two years of exit cohorts old enough that we can measure this accurately — more recent exits haven't had six months to potentially return yet.",
  ];

  return (
    <section className="section">
      <h2 className="section-heading">Length of Time Homeless</h2>
      <p className="section-subhead">How long are people experiencing homelessness, and is that changing?</p>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={setPopulationSegment} />
      </FilterBar>
      <Scrolly
        steps={steps}
        renderGraphic={() => (
          <div className="scrolly-graphic-stack">
            <LengthChart rows={scopedLength} />
            <ReturnCohortChart rows={scopedReturns} />
          </div>
        )}
      />
    </section>
  );
}
