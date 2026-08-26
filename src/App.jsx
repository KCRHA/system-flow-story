import { useEffect, useState } from "react";
import { loadDashboardData } from "./lib/loadData.js";
import ResourceAccessSection from "./components/sections/ResourceAccessSection.jsx";
import LengthSection from "./components/sections/LengthSection.jsx";
import OutflowSection from "./components/sections/OutflowSection.jsx";
import CapacitySection from "./components/sections/CapacitySection.jsx";

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadDashboardData().then(setData).catch(setError);
  }, []);

  if (error) return <div className="hero">Couldn't load dashboard data: {error.message}</div>;
  if (!data) return <div className="hero">Loading…</div>;

  return (
    <div>
      <header className="hero">
        <h1>King County's Homelessness System Flow</h1>
        <p>
          Data is one of our most powerful tools for ending homelessness. This dashboard follows how people move
          into, through, and out of King County's homelessness response system — who enters, who's active, who
          exits and to where, what resources people are able to reach along the way, how long people experience
          homelessness, and how much shelter and housing capacity exists to meet the need.
        </p>
      </header>
      <OutflowSection flowRows={data.flow} />
      <ResourceAccessSection flowRows={data.flow} />
      <LengthSection lengthRows={data.length} returnCohortRows={data.returnCohorts} />
      <CapacitySection capacityRows={data.capacity} capacityQuarterlyRows={data.capacityQuarterly} capacityYearlyRows={data.capacityYearly} />
    </div>
  );
}
