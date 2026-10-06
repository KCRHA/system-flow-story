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

// The measures the run chart (HomelessnessTrendChart) can plot — one per
// flow_type the quarterly export carries (see sankeyData.js's
// buildFlowPeriod), so switching here is just pointing the same per-quarter
// lookup at a different flow_type key rather than fetching anything new.
// `unitLabel` is the short noun phrase for "X people ___" in the chart's
// tooltips; `axisLabel` is the fuller phrase for the y-axis and section
// heading ("How has the number of people ___ changed over time?"). `yyaOnly`
// mirrors the "Aged Out" KPI card's own gating (see OutflowSection) — every
// other population segment's aged_out count is always 0. `group` names the
// <optgroup> MeasureSelect sorts each measure into (Active/Entered the
// system/Exited the system, matching OutflowSection's own KPI card row
// headings) — consecutive options sharing a group collapse into one
// <optgroup>, which is what actually draws the dividing line between them.
export const MEASURES = [
  { value: "experienced_homelessness", label: "Active in our system", unitLabel: "active", axisLabel: "active in our system", group: "Active" },
  {
    value: "indiv_newly_homeless",
    label: "Newly experiencing homelessness",
    unitLabel: "newly homeless",
    axisLabel: "newly experiencing homelessness",
    group: "Entered the system",
  },
  {
    value: "indiv_return_from_housed",
    label: "Returning from housing",
    unitLabel: "returning from housing",
    axisLabel: "returning from housing",
    group: "Entered the system",
  },
  {
    value: "indiv_return_from_inactive",
    label: "Returning from inactivity",
    unitLabel: "returning from inactivity",
    axisLabel: "returning from inactivity",
    group: "Entered the system",
  },
  { value: "indiv_inactive", label: "Inactive", unitLabel: "inactive", axisLabel: "inactive", group: "Exited the system" },
  { value: "indiv_permanently_housed", label: "Permanently housed", unitLabel: "permanently housed", axisLabel: "permanently housed", group: "Exited the system" },
  { value: "indiv_deceased", label: "Deceased", unitLabel: "deceased", axisLabel: "deceased", group: "Exited the system" },
  { value: "indiv_aged_out", label: "Aged Out", unitLabel: "aged out", axisLabel: "aged out", group: "Exited the system", yyaOnly: true },
];

export function MeasureSelect({ value, onChange, options = MEASURES }) {
  // Collapse consecutive same-group options into one <optgroup> each,
  // rather than grouping by every distinct group name globally — options
  // are already in Active/Entered/Exited order, so this is just folding
  // runs, and avoids re-sorting the list out of that order.
  const groups = [];
  for (const opt of options) {
    const current = groups.at(-1);
    if (current?.name === opt.group) current.items.push(opt);
    else groups.push({ name: opt.group, items: [opt] });
  }
  return (
    <label>
      Measure
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {groups.map((g) => (
          <optgroup key={g.name} label={g.name}>
            {g.items.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

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
