import {
  courseFacets,
  graduateLevels,
  undergraduateLevels,
} from "./course-facets";
import { courseTags, type CourseTag } from "./course-tags";
import { departmentLabel } from "./departments";
import { courseTitle } from "./format";
import { activityLabel } from "./course-learning";
import type { Status } from "./types";

export const dayLabels = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};
export const timeLabels = {
  morning: "Morning",
  afternoon: "Afternoon",
  evening: "Evening",
};
export const modeLabels = {
  in_person: "In person",
  online: "Online",
  mixed: "Mixed",
};
export const seasonLabels = {
  fall: "Fall",
  spring: "Spring",
  summer: "Summer",
};

export const filterGroups = [
  { id: "tags", label: "Tags", facets: ["tags"] },
  {
    id: "course",
    label: "Course details",
    facets: ["level", "credits", "requisites", "season", "designation"],
  },
  { id: "schedule", label: "Schedule", facets: ["days", "time", "mode"] },
  { id: "grades", label: "Grades", facets: ["gpa"] },
  { id: "instructor", label: "Instructor", facets: ["instructor"] },
] as const;

export function tokens(value = "") {
  return value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

function range(label: string, min?: string, max?: string, exclusive = false) {
  return `${label}: ${min && max ? `${min}–${exclusive ? "<" : ""}${max}` : min ? `≥ ${min}` : `${exclusive ? "<" : "≤"} ${max}`}`;
}

export function activeCourseFilters(
  filters: Record<string, string>,
  designations: NonNullable<Status["designations"]>,
  instructorName?: string | null,
) {
  const active = courseFacets.flatMap<{ id: string; label: string; keys: string[] }>((facet) => {
    const keys = facet.params.map((param) => param.name);
    if (
      !filters[keys[0]] &&
      !keys.some(
        (key) =>
          !["days_match", "gpa_max_exclusive"].includes(key) && filters[key],
      )
    )
      return [];
    const values = tokens(filters[keys[0]]);
    let label: string;
    switch (facet.id) {
      case "tags":
        label = values
          .map((value) => courseTags[value as CourseTag]?.label ?? value)
          .join(" + ");
        break;
      case "subject":
        label = values.map(departmentLabel).join(" or ");
        break;
      case "level": {
        const bands = values
          .map(Number)
          .sort((a, b) => a - b)
          .join(",");
        label =
          bands === undergraduateLevels.join(",")
            ? "Undergraduate"
            : bands === graduateLevels.join(",")
              ? "Graduate"
              : `Level: ${values.map((band) => `${band}–${Number(band) + 99}`).join(" or ")}`;
        break;
      }
      case "credits":
        label = range("Credits", filters.credits_min, filters.credits_max);
        break;
      case "gpa":
        label = range(
          "Historical GPA",
          filters.gpa_min,
          filters.gpa_max,
          filters.gpa_max_exclusive === "true",
        );
        break;
      case "requisites":
        label =
          filters.requisites === "none"
            ? "No requisites listed"
            : "Requisites listed";
        break;
      case "season":
        label = `Usually offered: ${values.map((value) => seasonLabels[value as keyof typeof seasonLabels]).join(" or ")}`;
        break;
      case "designation":
        label = values
          .map(
            (token) =>
              designations.find(
                (row) => `${row.family}:${row.value}` === token,
              )?.label ?? token,
          )
          .join(" or ");
        break;
      case "instructor":
        label = instructorName
          ? `Instructor: ${courseTitle(instructorName)}`
          : "Selected instructor";
        break;
      case "days":
        label = `${filters.days_match === "any" ? "Meets on" : "Only"} ${values.map((value) => dayLabels[value as keyof typeof dayLabels]).join(", ")}`;
        break;
      case "time":
        label = values
          .map((value) => timeLabels[value as keyof typeof timeLabels])
          .join(" or ");
        break;
      case "mode":
        label = values
          .map((value) => modeLabels[value as keyof typeof modeLabels])
          .join(" or ");
        break;
    }
    return [{ id: facet.id, label, keys }];
  });
  if (filters.activity)
    active.push({
      id: "activity",
      label: `Learning activity: ${activityLabel(filters.activity)}`,
      keys: ["activity"],
    });
  return active;
}
