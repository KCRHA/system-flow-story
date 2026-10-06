// "People who identify as X" (the user's specified phrasing) only reads
// naturally for the demographic types that really are an identity a person
// holds (race/ethnicity, gender, age). unsheltered_in_period and
// project_type_engagement are both situational categories, not identities
// — "people who identify as Unsheltered this period" or "...as Emergency
// Shelter" reads as a category-error, so each gets its own natural phrasing
// instead, matching how its own category labels actually read (see
// App.jsx's UNSHELTERED_CATEGORY_LABELS / PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS).
//
// Shared between any blurb/tooltip text that names who's being measured
// (LengthSection's chart blurbs, HomelessnessTrendChart's hover panel via
// OutflowSection) — a reader scoped to a demographic category by the
// filter bar above shouldn't have to scroll back up to be reminded who
// "people"/"X people" refers to.
export function subjectFor(demographicType, demographicCategory) {
  if (demographicType === "overall") return "people";
  if (demographicType === "unsheltered_in_period") {
    // demographicCategory is already "Unsheltered this period" / "Not
    // unsheltered this period" — lowercase the leading word so it reads as
    // a clause ("people who were unsheltered this period"), not a title.
    return `people who were ${demographicCategory.charAt(0).toLowerCase()}${demographicCategory.slice(1)}`;
  }
  if (demographicType === "project_type_engagement") {
    return `people engaged with ${demographicCategory} this period`;
  }
  return `people who identify as ${demographicCategory}`;
}
