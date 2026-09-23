const MONTH_ABBREV = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Same UTC-safe parsing as QuarterPills' quarterAbbrev — "YYYY-MM-DD" parses
// as UTC midnight, so reading the month back with getUTCMonth (not getMonth)
// avoids a local-timezone read shifting it.
function monthAbbrev(month) {
  return MONTH_ABBREV[new Date(month).getUTCMonth()];
}

/** `months`: ascending "YYYY-MM-DD" month-start strings for the currently
 * selected year (see monthsInYear). `selected`: one of `months`, or null
 * when no month pill is active (full year or a quarter is selected instead —
 * see OutflowSection's mutual-exclusivity handling between this and
 * QuarterPills). */
export default function MonthPills({ months, selected, onSelect }) {
  return (
    <div className="month-pills">
      {months.map((month) => (
        <button
          key={month}
          type="button"
          className={`month-pill${selected === month ? " is-active" : ""}`}
          onClick={() => onSelect(month)}
        >
          {monthAbbrev(month)}
        </button>
      ))}
    </div>
  );
}
