import { describe, it, expect, vi } from "vitest";
vi.mock("$app/environment", () => ({ building: true, dev: true }));
import {
  search,
  gradeRows,
  assertRevision,
  status,
} from "../../src/lib/server/data";
import { normalize, termName, safeUrl } from "../../src/lib/format";
import { requirementTree, requirementText } from "../../src/lib/requirements";
describe("course discovery", () => {
  it("normalizes student course aliases", () => {
    expect(normalize("CS 300")).toBe("COMPSCI300");
    expect(normalize("COMP SCI 300")).toBe("COMPSCI300");
  });
  it("ranks exact course codes first", async () => {
    for (const q of ["CS300", "CS 300", "COMP SCI 300"]) {
      const r = await search(
        new URL("http://localhost/search?q=" + encodeURIComponent(q)),
      );
      expect(r.items[0].course_id).toBe("COMPSCI 300");
    }
  });
  it("finds partial cross-list aliases", async () => {
    const r = await search(new URL("http://localhost/search?q=CS%2FECE%20759"));
    expect(r.items.some((c) => c.course_id.includes("759"))).toBe(true);
  });
  it("combines full text and department filters", async () => {
    const r = await search(
      new URL("http://localhost/search?q=programming&subject=COMPSCI"),
    );
    expect(r.items.some((c) => c.course_id === "COMPSCI 300")).toBe(true);
  });
  it("rejects malformed filters and pagination", async () => {
    await expect(
      search(new URL("http://localhost/search?gpa_min=nope")),
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      search(new URL("http://localhost/search?days=fundy")),
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      search(new URL("http://localhost/search?time=noon")),
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      search(new URL("http://localhost/search?mode=hybrid")),
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      search(new URL("http://localhost/search?designation=not%20a%20token")),
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      search(new URL("http://localhost/search?page=-1")),
    ).rejects.toMatchObject({ status: 400 });
  });
  it("combines subjects with OR and names a selected instructor", async () => {
    const either = await search(
      new URL("http://localhost/search?subject=COMPSCI,MATH&availability=all"),
    );
    expect(either.items.length).toBeGreaterThan(0);
    const found = await search(
      new URL("http://localhost/search?q=COMPSCI%20300&availability=all"),
    );
    expect(found.items[0].course_id).toBe("COMPSCI 300");
    const teacher = found.items[0].discovery?.instructors[0];
    expect(teacher?.uid).toBeTruthy();
    const taught = await search(
      new URL(
        `http://localhost/search?instructor=${encodeURIComponent(teacher!.uid)}&availability=all`,
      ),
    );
    expect(taught.instructor_name).toBeTruthy();
    expect(taught.items.some((course) => course.course_id === "COMPSCI 300")).toBe(
      true,
    );
    const missing = await search(
      new URL("http://localhost/search?instructor=instructor_missing&availability=all"),
    );
    expect(missing.total).toBe(0);
    expect(missing.instructor_name).toBeNull();
  });
  it("keeps unparsed requisites out of the no-requisite list", async () => {
    const open = await search(
      new URL(
        "http://localhost/search?q=COMPSCI%20300&requisites=none&availability=all",
      ),
    );
    expect(open.items.some((course) => course.course_id === "COMPSCI 300")).toBe(
      false,
    );
    const review = await search(
      new URL(
        "http://localhost/search?q=COMPSCI%20200&requisites=none&availability=all",
      ),
    );
    expect(review.items.some((course) => course.course_id === "COMPSCI 200")).toBe(
      false,
    );
  });
  it("rejects mixed revisions", async () => {
    await expect(
      assertRevision(new URL("http://localhost/api/search?revision=old")),
    ).rejects.toMatchObject({ status: 409 });
  });
  it("queries current instructor names", async () => {
    const r = await search(
      new URL("http://localhost/search?kind=instructor&q=Hobbes"),
    );
    expect(r.items.some((i) => i.name.includes("Hobbes"))).toBe(true);
  });
  it("uses course distributions separately from instructor sections", async () => {
    const r = await gradeRows(
      "course_28c3390ba944d49fd17f7c72",
      new URL("http://localhost/api"),
    );
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((g) => !g.grade_section_uid)).toBe(true);
  });
});
describe("presentation integrity", () => {
  it("formats academic term codes", () => {
    expect(termName("1272")).toBe("Fall 2026");
    expect(termName("1264")).toBe("Spring 2026");
  });
  it("does not render executable source URLs", () => {
    expect(safeUrl("javascript:alert(1)")).toBeUndefined();
    expect(safeUrl("https://example.com")).toBe("https://example.com/");
  });
  it("bounds graph traversal and retains condition nodes", () => {
    const ast = {
      root: "r",
      nodes: [
        { id: "r", kind: "any", children: ["a", "r"] },
        {
          id: "a",
          kind: "condition",
          condition: "Standing required",
          children: [],
        },
      ],
    };
    const tree = requirementTree(ast);
    expect(tree?.children).toHaveLength(1);
    expect(tree?.children[0].condition).toBe("Standing required");
  });
});

it("ranks eligible courses in both directions and rejects unknown collections", async () => {
  for (const ranking of ["easiest", "hardest"]) {
    const result = await search(
      new URL(
        `http://localhost/search?ranking=${ranking}&subject=COMPSCI&sort=gpa`,
      ),
    );
    expect(result.items.length).toBeGreaterThan(2);
    expect(result.items.every((c) => c.discovery.history.count >= 100)).toBe(
      true,
    );
    const gpas = result.items.map((c) => c.discovery.history.gpa);
    expect(gpas).toEqual(
      [...gpas].sort((a, b) => (ranking === "easiest" ? b - a : a - b)),
    );
    expect(result.items.every((c) => c.course_id.includes("COMPSCI"))).toBe(
      true,
    );
  }
  await expect(
    search(new URL("http://localhost/search?ranking=unknown")),
  ).rejects.toMatchObject({ status: 400 });
});

describe("catalog requirement typography", () => {
  it("separates joined catalog text without altering course numbers", () => {
    expect(
      requirementText(
        "MATH 217 or221.MATH\u00a0211or213does not fulfill the requisite.",
      ),
    ).toBe("MATH 217 or 221. MATH 211 or 213 does not fulfill the requisite.");
    expect(
      requirementText(
        "COMP SCI 200,220; placement intoCOMP SCI 300; 252andE C E 203",
      ),
    ).toBe("COMP SCI 200, 220; placement into COMP SCI 300; 252 and E C E 203");
    expect(
      requirementText("GPA 2.5; MATH 221 and a grade of BC or better."),
    ).toBe("GPA 2.5; MATH 221 and a grade of BC or better.");
  });
});

it("keeps autocomplete bounded and avoids grade/history enrichment", async () => {
  const { localDatabase } = await import("../../src/lib/server/database");
  const { interactionSchemas } = await import("../../src/lib/api/schemas");
  const db = await localDatabase();
  const prepare = vi.spyOn(db, "prepare");
  try {
    const result = await search(
      new URL("http://localhost/api/suggest?q=CS%20300&subject=COMPSCI"),
      undefined,
      true,
    );
    expect(result.items[0].course_id).toBe("COMPSCI 300");
    expect(result.items.length).toBeLessThanOrEqual(6);
    expect(result.items[0]).not.toHaveProperty("discovery");
    const statements = prepare.mock.calls
      .map(([sql]) => String(sql))
      .join("\n");
    expect(statements).not.toMatch(/grade_summaries|COUNT\(|SELECT.*payload/i);
    expect(
      interactionSchemas.Suggestions.parse({
        items: result.items,
        revision: "test",
      }).items[0],
    ).not.toHaveProperty("gpa");
  } finally {
    prepare.mockRestore();
  }
});
