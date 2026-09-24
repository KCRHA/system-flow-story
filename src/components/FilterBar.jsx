const POPULATION_SEGMENTS = [
  { value: "all_population", label: "All Population" },
  { value: "yya", label: "Youth and Young Adults" },
  { value: "chronic", label: "Chronically Homeless" },
  { value: "single_adults", label: "Single Adults" },
  { value: "veterans", label: "Veterans" },
  { value: "family", label: "Families with Children" },
];

// household_type is intentionally left out here — the user asked to start
// this filter with these three demographic types only, even though
// household_type exists as a full dimension in the exported data.
//
// age_category isn't offered for the YYA population segment (see App.jsx's
// demographicTypeOptions) — every person in that segment already falls in
// the same one or two age tiers by definition, so breaking it down further
// would be meaningless (mostly one 100% category and a lot of suppressed
// near-zero ones).
export const DEMOGRAPHIC_TYPES = [
  { value: "overall", label: "All" },
  { value: "race_ethnicity", label: "Race / Ethnicity" },
  { value: "gender_identity", label: "Gender Identity" },
  { value: "gender_alignment", label: "Gender Alignment" },
  { value: "age_category", label: "Age Category" },
  { value: "unsheltered_in_period", label: "Unsheltered This Period" },
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

export function DemographicTypeSelect({ value, onChange, options = DEMOGRAPHIC_TYPES }) {
  return (
    <label>
      Demographic
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

// Reactive to whichever demographic type is currently selected — `options`
// is the caller's own data-derived category list for that type (see
// App.jsx), not a hardcoded one, so it always matches what's actually in
// the export. Disabled once there's nothing to pick beyond "Overall".
export function DemographicCategorySelect({ options, value, onChange, disabled }) {
  return (
    <label>
      Category
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {disabled ? (
          <option value="Overall">Overall</option>
        ) : (
          options.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))
        )}
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
