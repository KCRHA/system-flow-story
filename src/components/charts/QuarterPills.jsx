// "YYYY-MM-DD" (a quarter's own start date, e.g. "2026-07-01" for Q3) parses
// as UTC midnight — reading the month back with getUTCMonth (not getMonth)
// avoids a local-timezone read shifting it, same concern ReturnCohortChart's
// quarterLabel already guards against.
function quarterAbbrev(quarter) {
  const q = Math.floor(new Date(quarter).getUTCMonth() / 3) + 1;
  return `Q${q}`;
}

/** `quarters`: ascending "YYYY-MM-DD" quarter-start strings for the
 * currently selected year (see quartersInYear — already excludes any
 * quarter still in progress). `selected`: one of `quarters`, or null when
 * no quarter is active. `fullYearActive`: whether "Full Year" itself is
 * the active period — distinct from `selected == null`, since a sibling
 * MonthPills row can also leave `selected` null while a month is active
 * (see OutflowSection's mutual-exclusivity handling); defaults to
 * `selected == null` for callers with no month row to worry about.
 * `throughLabel` ("Aug"), when given, suffixes the Full year pill as
 * "Full year (through Aug)" — OutflowSection passes this only when the
 * selected year is still in progress (dashboard_flow_quarterly never
 * carries an incomplete quarter, so there's no quarter pill covering those
 * trailing months — see its own trailingMonths/throughLabel comment). */
export default function QuarterPills({ quarters, selected, onSelect, fullYearActive = selected == null, throughLabel }) {
  return (
    <div className="month-pills">
      <button type="button" className={`month-pill${fullYearActive ? " is-active" : ""}`} onClick={() => onSelect(null)}>
        Full year{throughLabel ? ` (through ${throughLabel})` : ""}
      </button>
      {quarters.map((quarter) => (
        <button
          key={quarter}
          type="button"
          className={`month-pill${selected === quarter ? " is-active" : ""}`}
          onClick={() => onSelect(quarter)}
        >
          {quarterAbbrev(quarter)}
        </button>
      ))}
    </div>
  );
}
