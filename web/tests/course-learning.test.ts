import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import CourseLearning from "../../src/lib/components/CourseLearning.svelte";
import { activeCourseFilters } from "../../src/lib/course-filter-ui";
import {
  learningEvidence,
  supportedLearningClaims,
} from "../../src/lib/course-learning";

describe("evidence-backed course learning", () => {
  it("renders official outcomes, derived claims and source passages in initial HTML", () => {
    const html = render(CourseLearning, {
      props: {
        experimental: true,
        outcomes: [
          {
            text: "Analyze experimental data.",
            source: "UW Guide",
            source_url: "https://guide.wisc.edu/courses/chem/",
            catalog_year: "2026-2027",
          },
        ],
        skills: [
          {
            text: "Experimental data analysis",
            evidence: [
              {
                course_id: "CHEM 100",
                field: "official_learning_outcomes",
                outcome_index: 0,
                quote: "Analyze experimental data.",
                source: "UW Guide",
                source_url: "https://guide.wisc.edu/courses/chem/",
              },
            ],
          },
        ],
        activities: [
          {
            label: "data-analysis",
            text: "Analyzing experimental data",
            evidence: [
              {
                course_id: "CHEM 100",
                field: "official_learning_outcomes",
                outcome_index: 0,
                quote: "Analyze experimental data.",
                source: "UW Guide",
                source_url: "https://guide.wisc.edu/courses/chem/",
              },
            ],
          },
        ],
      },
    }).body;
    expect(html).toContain("Official learning outcomes");
    expect(html).toContain("Analyze experimental data.");
    expect(html).toContain("Experimental data analysis");
    expect(html).toContain("Data analysis");
    expect(html).toContain('href="https://guide.wisc.edu/courses/chem/"');
    expect(html).toContain("AI-derived from official course text");
    expect(html).toContain("Catalog 2026-2027");
  });

  it("keeps older datasets quiet and suppresses claims with no supporting quote", () => {
    expect(render(CourseLearning).body).not.toContain("What you can learn");
    const skills = [
      { text: "Unsupported skill" },
      { text: "Empty quote", citations: [{ quote: " " }] },
    ];
    expect(supportedLearningClaims(skills)).toEqual([]);
    expect(render(CourseLearning, { props: { skills } }).body).not.toContain(
      "Unsupported skill",
    );
  });

  it("renders unsafe source URLs as text without an active link", () => {
    const html = render(CourseLearning, {
      props: {
        outcomes: [
          {
            text: "Reason mathematically.",
            source: "Official source",
            source_url: "javascript:alert(1)",
          },
        ],
      },
    }).body;
    expect(html).toContain("Reason mathematically.");
    expect(html).not.toContain('href="javascript:');
  });

  it("offers a removable activity filter without requiring facet data", () => {
    expect(
      activeCourseFilters({ activity: "lab-work" }, [], undefined, true),
    ).toContainEqual({
      id: "activity",
      label: "Learning activity: Lab work",
      keys: ["activity"],
    });
  });
  it("preserves source context when evidence refers to an official outcome", () => {
    const evidence = learningEvidence(
      {
        text: "Analysis",
        evidence: [
          {
            field: "official_learning_outcomes",
            outcome_index: 0,
            quote: "Analyze data.",
            source_url: "https://guide.wisc.edu/courses/chem/",
          },
        ],
      },
      [
        {
          text: "Analyze data.",
          source: "UW Guide",
          source_url: "https://guide.wisc.edu/courses/chem/",
          catalog_year: "2026-2027",
        },
      ],
    );
    expect(evidence[0]).toMatchObject({
      source: "UW Guide",
      catalog_year: "2026-2027",
      source_url: "https://guide.wisc.edu/courses/chem/",
    });
  });
  it.each([
    { outcome_index: 1 },
    { outcome_index: -1 },
    { source_url: "https://guide.wisc.edu/courses/history/" },
    { source_url: null },
    { quote: "An older outcome that is no longer present." },
  ])("suppresses stale outcome citations in initial HTML: %j", (override) => {
    const outcomes = [
      {
        text: "Analyze data.",
        source: "UW Guide",
        source_url: "https://guide.wisc.edu/courses/chem/",
        catalog_year: "2026-2027",
      },
    ];
    const claim = {
      text: "Stale inferred skill",
      evidence: [
        {
          field: "official_learning_outcomes",
          outcome_index: 0,
          quote: "Analyze data.",
          source_url: outcomes[0].source_url,
          ...override,
        },
      ],
    };
    expect(learningEvidence(claim, outcomes)).toEqual([]);
    expect(supportedLearningClaims([claim], outcomes)).toEqual([]);
    const html = render(CourseLearning, {
      props: { outcomes, skills: [claim], experimental: true },
    }).body;
    expect(html).not.toContain("Stale inferred skill");
    expect(html).not.toContain("Supporting course text");
  });
  it("validates description citations against the current description without borrowing outcome metadata", () => {
    const claim = {
      text: "Programming",
      evidence: [
        {
          field: "description",
          quote: "Build programs.",
          catalog_year: "1900",
        },
      ],
    };
    expect(supportedLearningClaims([claim], [], "Write essays.")).toEqual([]);
    expect(
      learningEvidence(claim, [], "Build programs.")[0].catalog_year,
    ).toBeUndefined();
    expect(
      render(CourseLearning, {
        props: {
          skills: [claim],
          description: "Build programs.",
          experimental: true,
        },
      }).body,
    ).toContain("Programming");
  });
  it("publishes official outcomes while hiding experimental claims and activity chips by default", () => {
    const outcomes = [
      {
        text: "Analyze data.",
        source: "UW Guide",
        source_url: "https://guide.wisc.edu/courses/chem/",
      },
    ];
    const claim = {
      text: "Experimental data skill",
      evidence: [
        {
          field: "official_learning_outcomes",
          outcome_index: 0,
          quote: "Analyze data.",
          source_url: outcomes[0].source_url,
        },
      ],
    };
    const html = render(CourseLearning, {
      props: { outcomes, skills: [claim], activities: [claim] },
    }).body;
    expect(html).toContain("Official learning outcomes");
    expect(html).toContain("Analyze data.");
    expect(html).not.toContain("Experimental data skill");
    expect(html).not.toContain("Skills and activities");
    expect(activeCourseFilters({ activity: "lab-work" }, [])).toEqual([]);
  });
});
