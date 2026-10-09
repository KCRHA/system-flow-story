// "People who identify as X" (the user's specified phrasing) only reads
// naturally for the demographic types that really are an identity a person
// holds (race/ethnicity, gender, age). unsheltered_in_period and
// project_type_engagement are both situational categories, not identities
// — "people who identify as Unsheltered this period" or "...as Emergency
// Shelter" reads as a category-error, so each gets its own natural phrasing
// instead, matching how its own category labels actually read (see
// App.jsx's UNSHELTERED_CATEGORY_LABELS / PROJECT_ENGAGEMENT_CATEGORY_DIMENSIONS).
//
// Mirrors FilterBar's POPULATION_SEGMENTS, lowercased into the noun phrase
// each segment reads as mid-sentence ("all_population" falls back to plain
// "people" — every other segment already names who it is, so no "people"
// is needed alongside it).
const POPULATION_NOUNS = {
  all_population: "people",
  yya: "youth and young adults",
  chronic: "chronically homeless people",
  single_adults: "single adults",
  veterans: "veterans",
  family: "families with children",
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
  return `${noun} who identify as ${demographicCategory}`;
}
