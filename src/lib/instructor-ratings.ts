// The prior has the weight of 20 valid quality ratings. It is a transparent
// smoothing choice, not a minimum review requirement or a confidence interval.
import policy from "./search-policy.json";
export const ratingPriorWeight = policy.ratingPriorWeight;
export function bayesianRating(
  mean: number | null | undefined,
  count: number,
  prior: number | null,
) {
  if (
    mean == null ||
    prior == null ||
    !Number.isFinite(mean) ||
    mean < 1 ||
    mean > 5 ||
    !Number.isFinite(count) ||
    count <= 0
  )
    return null;
  return (
    (mean * count + prior * ratingPriorWeight) / (count + ratingPriorWeight)
  );
}
export function adjustInstructorRating(ratings: any, prior: number | null) {
  if (!ratings) return ratings;
  return {
    ...ratings,
    bayesian_quality: bayesianRating(
      ratings.quality,
      ratings.quality_count ?? 0,
      prior,
    ),
    prior_mean: prior,
    prior_weight: ratingPriorWeight,
  };
}
