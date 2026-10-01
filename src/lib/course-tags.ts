import policy from "./search-policy.json";

export const tagThresholds = policy.tagThresholds;

export const courseTagValues = [
  "small-lectures",
  "higher-grades",
  "rated-teacher",
  "large-lectures",
  "lower-grades",
] as const;
export type CourseTag = (typeof courseTagValues)[number];

export const courseTags: Record<
  CourseTag,
  { label: string; description: string }
> = {
  "small-lectures": {
    label: "Small lectures",
    description:
      "Median enrollment of 30 or fewer in recorded lectures this term.",
  },
  "higher-grades": {
    label: "Higher grades",
    description:
      "Latest released GPA at least 0.20 above the comparison, with 30+ letter grades.",
  },
  "rated-teacher": {
    label: "Highly rated instructor",
    description:
      "An assigned instructor has adjusted quality of 4.0/5 or higher from 10+ ratings.",
  },
  "large-lectures": {
    label: "Large lectures",
    description:
      "Median enrollment of 100 or more in recorded lectures this term.",
  },
  "lower-grades": {
    label: "Lower grades",
    description:
      "Latest released GPA at least 0.20 below the comparison, with 30+ letter grades.",
  },
};
