import { describe, expect, it } from "vitest";
import { DatabaseSync } from "node:sqlite";
import {
  compileCourseQuery,
  parseCourseFilters,
} from "../../src/lib/server/course-query";

const term = "1272";

function filters(search: string) {
  return parseCourseFilters(new URLSearchParams(search), term, "offered");
}

function compile(search: string, availability: "offered" | "all" = "offered") {
  return compileCourseQuery(
    parseCourseFilters(new URLSearchParams(search), term, availability),
  );
}

describe("course filter compiler", () => {
  it("accepts boundary values and rejects malformed ones", () => {
    expect(
      filters("gpa_min=4&gpa_max=0&level=0,900&credits_min=0&credits_max=20")
        .gpaMin,
    ).toBe(4);
    expect(filters("level=0,900").levels).toEqual([0, 900]);
    expect(
      filters(
        `subject=${Array.from({ length: 12 }, (_, i) => `S${i}`).join(",")}`,
      ).subjects,
    ).toHaveLength(12);
    for (const search of [
      "tags=easy",
      "activity=easy",
      "activity=writing,programming",
      "tags=small-lectures,unknown",
      "gpa_min=nope",
      "gpa_min=4.1",
      "gpa_max_exclusive=yes",
      "credits_max=21",
      "days=fundy",
      "time=noon",
      "mode=hybrid",
      "days_match=sideways",
      "designation=not a token",
      "level=50",
      "requisites=open",
      "season=winter",
      `subject=${Array.from({ length: 13 }, (_, i) => `S${i}`).join(",")}`,
    ]) {
      expect(() => filters(search), search).toThrowError(
        expect.objectContaining({ status: 400 }),
      );
    }
  });

  it("requires every selected tag and deduplicates repeated values", () => {
    const compiled = compile(
      "tags=small-lectures,higher-grades,small-lectures",
      "all",
    );
    expect(compiled.values).toEqual(["small-lectures", "higher-grades"]);
    expect(compiled.where.match(/EXISTS/g)).toHaveLength(2);
    expect(compiled.history).toBe(false);
  });

  it("binds activity classification and leaves older documents unmatched", () => {
    const compiled = compile("activity=programming", "all");
    expect(compiled.where).toContain("json_each(c.payload, '$.activity_tags')");
    expect(compiled.values).toEqual(["programming"]);
    expect(compiled.where).not.toContain("programming");
    expect(filters("activity=writing").activity).toBe("writing");
  });

  it("matches only the selected activity and tolerates older course payloads", () => {
    const db = new DatabaseSync(":memory:");
    try {
      db.exec("CREATE TABLE courses(uid TEXT,payload TEXT)");
      const insert = db.prepare("INSERT INTO courses VALUES(?,?)");
      insert.run("old", JSON.stringify({ description: "Programs" }));
      insert.run(
        "writing",
        JSON.stringify({ activity_tags: [{ text: "writing" }] }),
      );
      insert.run(
        "programming",
        JSON.stringify({
          activity_tags: [{ text: "programming", evidence: [] }],
        }),
      );
      const compiled = compile("activity=programming", "all");
      expect(
        db
          .prepare(`SELECT uid FROM courses c WHERE 1=1${compiled.where}`)
          .all(...(compiled.values as string[])),
      ).toEqual([{ uid: "programming" }]);
    } finally {
      db.close();
    }
  });

  it("compiles graduate bands as course-number ranges", () => {
    const compiled = compile("level=700,800,900");
    expect(compiled.where).toContain("BETWEEN ? AND ?");
    expect(compiled.values).toEqual([700, 799, 800, 899, 900, 999, term]);
    expect(compiled.history).toBe(false);
  });
  it("supports exclusive GPA maxima for histogram bins without changing manual inclusive bounds", () => {
    expect(
      compile("gpa_min=3.5&gpa_max=3.6&gpa_max_exclusive=true", "all").where,
    ).toContain("h.history_gpa<?");
    expect(compile("gpa_min=3.5&gpa_max=3.6", "all").where).toContain(
      "h.history_gpa<=?",
    );
    expect(compile("gpa_max_exclusive=true", "all").history).toBe(false);
  });

  it("compiles a full query as one predicate list and one history flag", () => {
    const compiled = compile(
      "designation=breadth:natural-science&level=300,700&gpa_min=3.2&gpa_max=4&mode=in_person&days=mon,wed&time=morning,evening",
    );
    expect(compiled.history).toBe(true);
    expect(compiled.where.match(/history_gpa/g)).toHaveLength(2);
    expect(compiled.where).not.toContain("WITH history");
    expect(compiled.where).not.toContain("json_extract");
    expect(compiled.where).toContain("course_designations");
    expect(compiled.where).toContain("section_modes");
    expect(compiled.where).toContain("NOT EXISTS");
  });

  it("treats days_match as a set constraint or as any meeting", () => {
    const within = compile("days=mon");
    const any = compile("days=mon&days_match=any");
    expect(within.where).toContain("NOT IN");
    expect(any.where).not.toContain("NOT IN");
    expect(any.where).toContain("class_meetings");
  });

  it("binds the instructor to the selected term only for recorded offerings", () => {
    expect(compile("instructor=person").where).toContain("t.term=?");
    expect(compile("instructor=person", "all").where).not.toContain("t.term=?");
    expect(compile("instructor=person", "all").values).toEqual(["person"]);
  });

  it("ORs subjects and keeps credit comparisons on the opposite column", () => {
    const compiled = compile(
      "subject=COMPSCI,MATH&credits_min=3&credits_max=3",
      "all",
    );
    expect(compiled.where).toContain("s.subject IN (?,?)");
    expect(compiled.where).toContain("c.credits_max>=?");
    expect(compiled.where).toContain("c.credits_min<=?");
    expect(compiled.values).toEqual(["COMPSCI", "MATH", 3, 3]);
  });
});
