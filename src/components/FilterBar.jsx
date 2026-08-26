const POPULATION_SEGMENTS = [
  { value: "all_population", label: "All Population" },
  { value: "yya", label: "Youth and Young Adults" },
  { value: "chronic", label: "Chronically Homeless" },
  { value: "single_adults", label: "Single Adults" },
  { value: "veterans", label: "Veterans" },
];

const DIMENSIONS = [
  { value: "overall", label: "Overall" },
  { value: "race_ethnicity", label: "Race / Ethnicity" },
  { value: "gender", label: "Gender" },
  { value: "household_type", label: "Household Type" },
];

export function PopulationSegmentSelect({ value, onChange }) {
  return (
    <label>
      Population
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {POPULATION_SEGMENTS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function DimensionSelect({ value, onChange }) {
  return (
    <label>
      Break down by
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {DIMENSIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function YearSelect({ years, value, onChange }) {
  return (
    <label>
      Year
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {years.map((year) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function FilterBar({ children }) {
  return <div className="filter-bar">{children}</div>;
}
