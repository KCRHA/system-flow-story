import { useMemo } from "react";
import Scrolly from "../Scrolly.jsx";
import LengthChart from "../charts/LengthChart.jsx";
import ReturnCohortChart from "../charts/ReturnCohortChart.jsx";
import { filterRows } from "../../lib/loadData.js";
import { subjectFor } from "../../lib/demographics.js";

export default function LengthSection({
  lengthRows,
  returnCohortRows,
  populationSegment,
  demographicType,
  demographicCategory,
  filterDimension,
  filterCategory,
  year,
}) {
  // Last 2 years, ending at the selected Year (e.g. picking 2024 ends the
  // window at Dec 2024, not the latest month overall) — same Year selector
  // OutflowSection/CapacitySection use, so switching years moves every
  // time-series chart on the page together. Full history is available but
  // a shorter trailing window keeps this legible.
  const scopedLength = useMemo(
    () =>
      filterRows(lengthRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => Number(r.month.slice(0, 4)) <= year)
        .sort((a, b) => a.month.localeCompare(b.month))
        .slice(-24),
    [lengthRows, populationSegment, filterDimension, filterCategory, year]
  );
  // Only cohorts whose 6-month return window has fully elapsed have a
  // reportable rate at all (see window_complete in dashboard_return_cohorts.json)
  // — everything more recent is excluded rather than shown as a partial/
  // misleading rate. The most recent 8 of those complete quarters (ending
  // at the selected Year, same as scopedLength above) is what actually
  // renders, i.e. roughly the last 2 years.
  const scopedReturns = useMemo(
    () =>
      filterRows(returnCohortRows, { populationSegment, dimension: filterDimension, category: filterCategory })
        .filter((r) => r.window_complete && Number(r.exit_quarter.slice(0, 4)) <= year)
        .sort((a, b) => a.exit_quarter.localeCompare(b.exit_quarter))
        .slice(-8),
    [returnCohortRows, populationSegment, filterDimension, filterCategory, year]
  );

  // Scoping to a demographic category isn't visible once a reader has
  // scrolled past the filter controls above (OutflowSection), so the
  // blurb text says who's being measured explicitly — see subjectFor above.
  const subject = subjectFor(demographicType, demographicCategory);

  const steps = [
    `Among ${subject} active in the system each month, how long have they been experiencing homelessness so far, and is that changing over time? The line shows the median; the shaded band shows where the middle 50% of people fall.`,
    `A related question: of ${subject} who exit to permanent housing, how many return to homelessness within six months? Shown here are the last two years of exit cohorts old enough that we can measure this accurately. More recent exits haven't had six months to potentially return yet.`,
  ];

  return (
    <section className="section">
      <h2 className="section-heading">Length of Time Homeless</h2>
      <p className="section-subhead">How long are people experiencing homelessness, and is that changing?</p>
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
