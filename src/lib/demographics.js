// "People who identify as X" (the user's specified phrasing) only reads
// naturally for the demographic types that really are an identity a person
// holds (race/ethnicity, gender). unsheltered_in_period,
// project_type_engagement, and engaged_in_subregion are all situational
// categories, not identities — "people who identify as Unsheltered this
// period", "...as Emergency Shelter", or "...as Seattle Metro" all read as
// a category-error, so each gets its own natural phrasing instead, matching
// how its own category labels actually read (see App.jsx's
// UNSHELTERED_CATEGORY_LABELS / PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS /
// ENGAGED_IN_SUBREGION_CATEGORY_DIMENSIONS).
// last_known_subregion is geographic, not an identity either — "people who
// identify as South King County" reads the same way, so it gets its own
// clause too. (last_known_city would read the same way, but that filter is
// temporarily disabled — see subjectFor below.) age_category is a range,
// not an identity — "people aged 0 to 11" gets its own clause too.
//
// Mirrors FilterBar's POPULATION_SEGMENTS, lowercased into the noun phrase
// each segment reads as mid-sentence ("all_population" falls back to plain
// "people" — every other segment already names who it is, so no "people"
// is needed alongside it).
const POPULATION_NOUNS = {
  all_population: "people",
  yya: "youth and young adults",
  seniors: "seniors",
  chronic: "chronically homeless people",
  single_adults: "single adults",
  veterans: "veterans",
  family: "families with children",
};

// household_type categories (App.jsx's HOUSEHOLD_TYPE_CATEGORY_DIMENSIONS) -> the clause
// that follows the population noun.
const HOUSEHOLD_TYPE_SUBJECTS = {
  "Adults and Children": "in households with adults and children",
  "Adults Only": "in adult-only households",
  "Children Only": "in child-only households",
};

// Shared between any blurb/tooltip text that names who's being measured
// (LengthSection's chart blurbs, HomelessnessTrendChart's hover panel via
// OutflowSection) — a reader scoped to a population segment and/or a
// demographic category by the filter bar above shouldn't have to scroll
// back up to be reminded who "people"/"X people" refers to. The population
// segment picks the base noun (e.g. "veterans"), the demographic category
// narrows it further (e.g. "veterans who identify as Black/African
// American") — both scopes get named, not just one.
export function subjectFor(populationSegment, demographicType, demographicCategory) {
  const noun = POPULATION_NOUNS[populationSegment] ?? "people";
  if (demographicType === "overall") return noun;
  if (demographicType === "unsheltered_in_period") {
    // demographicCategory is already "Unsheltered this period" / "Not
    // unsheltered this period" — lowercase the leading word so it reads as
    // a clause ("... who were unsheltered this period"), not a title.
    return `${noun} who were ${demographicCategory.charAt(0).toLowerCase()}${demographicCategory.slice(1)}`;
  }
  if (demographicType === "project_type_engagement") {
    return `${noun} engaged with ${demographicCategory} this period`;
  }
  if (demographicType === "engaged_in_subregion") {
    return `${noun} who accessed services in ${demographicCategory} this period`;
  }
  // last_known_city filter temporarily disabled — was: `demographicType === "last_known_subregion" || demographicType === "last_known_city"`
  if (demographicType === "last_known_subregion") {
    return `${noun} last known to live in ${demographicCategory}`;
  }
  if (demographicType === "household_type") {
    // A household composition, not an identity — same reasoning as the
    // other situational branches.
    const phrase = HOUSEHOLD_TYPE_SUBJECTS[demographicCategory];
    if (phrase) return `${noun} ${phrase}`;
  }
  if (demographicType === "age_category") {
    // Age tiers ("0 to 11", "65 or Above") are a range, not an identity —
    // "who identify as 0 to 11" reads as a category-error, same reasoning
    // as the other situational branches above.
    return `${noun} aged ${demographicCategory}`;
  }
  return `${noun} who identify as ${demographicCategory}`;
}
