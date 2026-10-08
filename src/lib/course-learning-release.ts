/** Promote experimental features only after the documented pilot acceptance. */
export interface CourseLearningRelease {
  derivedClaims: boolean;
  activitySearch: boolean;
}

// Official outcomes are always available; this release publishes no new inferred features.
export const courseLearningRelease: Readonly<CourseLearningRelease> =
  Object.freeze({
    derivedClaims: false,
    activitySearch: false,
  });
