const POPULATION_SEGMENTS = [
  { value: "all_population", label: "All population" },
  { value: "yya", label: "Youth and Young Adults" },
  { value: "seniors", label: "Seniors" },
  { value: "chronic", label: "Chronically Homeless" },
  { value: "single_adults", label: "Single Adults" },
  { value: "veterans", label: "Veterans" },
  { value: "family", label: "Families with Children" },
];

// age_category is offered for every population segment, including YYA and
// Seniors — App.jsx's YYA_AGE_CATEGORIES/SENIORS_AGE_CATEGORIES narrow its
// *options* to the tiers each segment can actually contain (YYA: "0 to 11",
// "12 to 17", "18 to 24"; Seniors: "55 to 64", "65 or Above") rather than
// hiding the filter outright, since the split within each segment's own
// tiers is real variation, not a redundant restatement of the segment
// boundary.
export const DEMOGRAPHIC_TYPES = [
  { value: "overall", label: "All" },
  { value: "race_ethnicity", label: "Race / Ethnicity" },
  { value: "gender_identity", label: "Gender Identity" },
  { value: "gender_alignment", label: "Gender Alignment" },
  { value: "age_category", label: "Age Category" },
  { value: "unsheltered_in_period", label: "Unsheltered This Period" },
  { value: "project_type_engagement", label: "Project Type Engagement" },
  { value: "last_known_subregion", label: "Last Known Subregion" },
  { value: "engaged_in_subregion", label: "Engaged in Subregion" },
  // { value: "last_known_city", label: "Last Known City" },  // last_known_city filter temporarily disabled
];

// The measures the run chart (HomelessnessTrendChart) can plot — one per
// flow_type the quarterly export carries (see sankeyData.js's
// buildFlowPeriod), so switching here is just pointing the same per-quarter
// lookup at a different flow_type key rather than fetching anything new.
// The two "(total)" entries are the exception: there's no single flow_type
// for "everyone who entered"/"everyone who exited" in the export, so instead
// of a `value` naming one flow_type, they carry a `components` list of the
// indiv_* flow_types that partition it — OutflowSection's trendPoints sums
// those per quarter instead (see sankeyData.js's sumCellsForQuarter).
// `unitLabel` is the short noun phrase for "X people ___" in the chart's
// tooltips; `axisLabel` is the fuller phrase for the y-axis and section
// heading ("How has the number of people ___ changed over time?"). `yyaOnly`
// mirrors the "Aged Out" KPI card's own gating (see OutflowSection) — every
// other population segment's aged_out count is always 0 (and so doesn't
// move the "Exited the system (total)" composite above, even though it's
// always one of that total's components). `group` names the <optgroup>
// MeasureSelect sorts each measure into (Active/Entered the system/Exited
// the system, matching OutflowSection's own KPI card row headings) —
// consecutive options sharing a group collapse into one <optgroup>, which
// is what actually draws the dividing line between them.
export const MEASURES = [
  { value: "experienced_homelessness", label: "Active in our system", unitLabel: "active", axisLabel: "active in our system", group: "Active" },
  {
    value: "total_entered_the_system",
    label: "Entered the system (total)",
    unitLabel: "entering the system",
    axisLabel: "entering the system",
    group: "Entered the system",
    components: ["indiv_newly_homeless", "indiv_return_from_housed", "indiv_return_from_inactive"],
  },
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
  {
    value: "total_exited_the_system",
    label: "Exited the system (total)",
    unitLabel: "exiting the system",
    axisLabel: "exiting the system",
    group: "Exited the system",
    components: ["indiv_inactive", "indiv_permanently_housed", "indiv_aged_out"],
  },
  // Inactive includes deceased; deceasedFlowType is the band of how many
  // (see OutflowSection's trendPoints).
  {
    value: "indiv_inactive",
    label: "Inactive",
    unitLabel: "inactive",
    axisLabel: "inactive",
    group: "Exited the system",
    deceasedFlowType: "deceased_in_inactive",
  },
  { value: "indiv_permanently_housed", label: "Permanently housed", unitLabel: "permanently housed", axisLabel: "permanently housed", group: "Exited the system" },
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
