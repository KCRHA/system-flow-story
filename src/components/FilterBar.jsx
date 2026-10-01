const POPULATION_SEGMENTS = [
  { value: "all_population", label: "All population" },
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
  { value: "project_type_engagement", label: "Project Type Engagement" },
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
      Demographic/Characteristic
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
// `info`, when given (see OutflowSection's demographicNote), renders an
// InfoIcon next to the label — omitted entirely whenever the current
// demographic type needs no clarification.
export function DemographicCategorySelect({ options, value, onChange, disabled, info }) {
  return (
    <label>
      <span className="filter-bar-label-text">
        Category
        {info}
      </span>
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

// `partialYears` (a Set of year numbers), when given, suffixes those
// options as "2026 (partial year)" — OutflowSection passes the years that
// don't yet have all 4 quarters present in dashboard_flow_quarterly (same
// signal QuarterPills' own throughLabel uses for the Full year pill).
export function YearSelect({ years, value, onChange, partialYears }) {
  return (
    <label>
      Year
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {years.map((year) => (
          <option key={year} value={year}>
            {year}
            {partialYears?.has(year) ? " (partial year)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function FilterBar({ children }) {
  return <div className="filter-bar">{children}</div>;
}
