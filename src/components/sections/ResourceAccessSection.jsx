import { useMemo, useState } from "react";
import Scrolly from "../Scrolly.jsx";
import ResourceAccessChart, { PHASES, PHASE_LABELS, PHASE_COLORS } from "../charts/ResourceAccessChart.jsx";
import FilterBar, { PopulationSegmentSelect } from "../FilterBar.jsx";
import ChartLegend from "../ChartLegend.jsx";
import { filterRows, distinctValues, resolveCell } from "../../lib/loadData.js";

const RESOURCE_TYPES = ["outreach", "emergency_shelter", "transitional_housing", "rapid_rehousing", "psh", "prevention"];

export default function ResourceAccessSection({ flowRows }) {
  const [populationSegment, setPopulationSegment] = useState("all_population");

  const scoped = useMemo(
    () => filterRows(flowRows, { populationSegment, dimension: "overall", category: "Overall" }),
    [flowRows, populationSegment]
  );
  // Last 2 years only — full history is available but a shorter trailing
  // window keeps this legible.
  const months = useMemo(() => distinctValues(scoped, "month").sort().slice(-24), [scoped]);

  const series = useMemo(() => {
    const cellFor = (month, flow_type) => resolveCell(scoped.find((r) => r.month === month && r.flow_type === flow_type));
    return RESOURCE_TYPES.map((type) => ({
      project_type: type,
      points: months.map((month) => ({
        month,
        ...Object.fromEntries(PHASES.map((phase) => [phase, cellFor(month, `resource_${type}_${phase}`)])),
      })),
    }));
  }, [months, scoped]);

  const legendItems = PHASES.map((phase) => ({ color: PHASE_COLORS[phase], label: PHASE_LABELS[phase] }));

  const steps = [
    {
      text: "Once someone is in the system, which resources can they actually reach? Outreach, emergency shelter, transitional housing, rapid re-housing, permanent supportive housing, and homelessness prevention each serve a different role in helping people find stability.",
      extra: <ChartLegend items={legendItems} />,
    },
    "For each resource type, watch three lines over time: how many people were newly enrolled in a month, how many were engaged at any point that month, and how many exited.",
  ];

  return (
    <section className="section">
      <h2 className="section-heading">Resource Access</h2>
      <p className="section-subhead">What resources can people experiencing homelessness actually access, and how has that changed over time?</p>
      <FilterBar>
        <PopulationSegmentSelect value={populationSegment} onChange={setPopulationSegment} />
      </FilterBar>
      <Scrolly steps={steps} renderGraphic={() => <ResourceAccessChart series={series} />} />
    </section>
  );
}
