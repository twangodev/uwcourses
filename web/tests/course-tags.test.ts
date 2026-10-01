import { DatabaseSync } from "node:sqlite";
import { describe, expect, it } from "vitest";
import { courseBadges } from "../../src/lib/badges";
import { courseTagValues } from "../../src/lib/course-tags";
import { bayesianRating } from "../../src/lib/instructor-ratings";
import {
  cohortBenchmarks,
  type GradePeer,
} from "../../src/lib/grade-benchmarks";
import { parseCourseFilters } from "../../src/lib/server/course-query";
import { courseTagScope } from "../../src/lib/server/course-tags";

const term = "1272";
const prior = 3.5;

// Ten equal-weight peers, threshold observations, duplicates, and a sparse latest release.
function fixture() {
  const db = new DatabaseSync(":memory:");
  db.exec(`CREATE TABLE courses(uid TEXT PRIMARY KEY,payload TEXT);
    CREATE TABLE subjects(uid TEXT,subject TEXT);
    CREATE TABLE grade_summaries(uid TEXT,term TEXT,a INTEGER,ab INTEGER,b INTEGER,bc INTEGER,c INTEGER,d INTEGER,f INTEGER);
    CREATE TABLE instructors(uid TEXT PRIMARY KEY,payload TEXT);
    CREATE TABLE teaching(course_uid TEXT,instructor_uid TEXT,term TEXT);`);
  const peers: GradePeer[] = [];
  const courses: any[] = [];
  for (let index = 0; index < 12; index++) {
    const uid = String(index);
    const sections =
      index === 0
        ? [
            {
              section_uid: "duplicate",
              term_id: term,
              section_type: "LEC",
              enrolled: 100,
            },
            {
              section_uid: "duplicate",
              term_id: term,
              section_type: "LEC",
              enrolled: 20,
            },
            {
              section_uid: "other",
              term_id: term,
              section_type: "LEC",
              enrolled: 40,
            },
            { term_id: term, section_type: "DIS", enrolled: 200 },
            { term_id: "1264", section_type: "LEC", enrolled: 200 },
          ]
        : [
            {
              section_uid: uid,
              term_id: term,
              section_type: "LEC",
              enrolled: index === 1 ? 100 : index === 2 ? 0 : 31,
            },
          ];
    const course = { course_uid: uid, course_id: `TEST ${index}`, sections };
    courses.push(course);
    db.prepare("INSERT INTO courses VALUES (?,?)").run(
      uid,
      JSON.stringify(course),
    );
    db.prepare("INSERT INTO subjects VALUES (?,?)").run(uid, "TEST");
    if (index === 0)
      db.prepare("INSERT INTO subjects VALUES (?,?)").run(uid, "OTHER");
    const a = index === 0 ? 30 : 0,
      b = index === 0 ? 0 : 30;
    db.prepare("INSERT INTO grade_summaries VALUES (?,?,?,0,?,0,0,0,0)").run(
      uid,
      "1264",
      a,
      b,
    );
    peers.push({
      uid,
      term: "1264",
      count: 30,
      gpa: index === 0 ? 4 : 3,
      subjects: index === 0 ? ["TEST", "OTHER"] : ["TEST"],
      topShare: 0,
    });
    if (index === 2) {
      db.prepare("INSERT INTO grade_summaries VALUES (?,?,29,0,0,0,0,0,0)").run(
        uid,
        term,
      );
      peers.push({
        uid,
        term,
        count: 29,
        gpa: 4,
        subjects: ["TEST"],
        topShare: 0,
      });
    }
  }
  for (const [uid, quality, count, assignedTerm] of [
    ["0", 5, 10, term],
    ["1", 5, 9, term],
    ["2", 5, 50, "1274"],
    ["3", 5, 11, term],
  ] as const) {
    db.prepare("INSERT INTO instructors VALUES (?,?)").run(
      uid,
      JSON.stringify({ ratings: { quality, quality_count: count } }),
    );
    db.prepare("INSERT INTO teaching VALUES (?,?,?)").run(
      uid,
      uid,
      assignedTerm,
    );
  }
  return { db, courses, peers };
}

describe("course tag evidence", () => {
  it("matches the badge definitions for medians, adjusted ratings, cohorts and latest released grades", () => {
    const { db, courses, peers } = fixture();
    for (const subject of ["", "TEST", "OTHER"]) {
      const filters = parseCourseFilters(
        new URLSearchParams(subject ? `subject=${subject}` : ""),
        term,
        "all",
      );
      const scope = courseTagScope(filters, courseTagValues, prior);
      const rows = db
        .prepare(`WITH ${scope.ctes.join(",")} SELECT uid,tag FROM course_tags`)
        .all(...(scope.values as any[])) as { uid: string; tag: string }[];
      const expected = courses
        .filter(
          (course) =>
            !subject ||
            peers.some(
              (peer) =>
                peer.uid === course.course_uid &&
                peer.subjects.includes(subject),
            ),
        )
        .flatMap((course) => {
          const terms = Object.fromEntries(
            peers
              .filter((peer) => peer.uid === course.course_uid)
              .map((peer) => [peer.term, peer]),
          );
          const benchmarks = {
            terms: Object.fromEntries(
              [...new Set(peers.map((peer) => peer.term))].map((term) => [
                term,
                cohortBenchmarks(peers.filter((peer) => peer.term === term)),
              ]),
            ),
          };
          const teachers = db
            .prepare(
              "SELECT i.payload,t.term FROM instructors i JOIN teaching t ON t.instructor_uid=i.uid WHERE t.course_uid=?",
            )
            .all(course.course_uid)
            .map((row) => {
              const ratings = JSON.parse(row.payload as string).ratings;
              return {
                name: course.course_uid,
                terms: [{ term: row.term as string }],
                ratings: {
                  quality_count: ratings.quality_count,
                  bayesian_quality: bayesianRating(
                    ratings.quality,
                    ratings.quality_count,
                    prior,
                  ),
                },
              };
            });
          return courseBadges({
            course,
            context: { terms, benchmarks },
            term,
            scope: subject || "school",
            instructors: teachers,
          }).map((badge) => `${course.course_uid}:${badge.tag}`);
        });
      expect(
        rows
          .filter(
            (row) =>
              !subject ||
              peers.some(
                (peer) =>
                  peer.uid === row.uid && peer.subjects.includes(subject),
              ),
          )
          .map((row) => `${row.uid}:${row.tag}`)
          .sort(),
      ).toEqual(expected.sort());
    }
    const scope = courseTagScope(
      parseCourseFilters(new URLSearchParams(), term, "all"),
      courseTagValues,
      prior,
    );
    const rows = db
      .prepare(`WITH ${scope.ctes.join(",")} SELECT uid,tag FROM course_tags`)
      .all(...(scope.values as any[])) as { uid: string; tag: string }[];
    expect(rows).toContainEqual({ uid: "0", tag: "small-lectures" });
    expect(rows).toContainEqual({ uid: "1", tag: "large-lectures" });
    expect(rows).toContainEqual({ uid: "0", tag: "rated-teacher" });
    expect(rows.filter((row) => row.uid === "2")).toEqual([]);
    expect(
      rows.some((row) => row.uid === "1" && row.tag === "rated-teacher"),
    ).toBe(false);
    db.close();
  });

  it("includes the exact 0.20 grade difference and keeps sparse latest terms excluded", () => {
    const { db } = fixture();
    db.exec(
      "UPDATE grade_summaries SET a=6,b=24 WHERE term='1264'; UPDATE grade_summaries SET a=12,b=18 WHERE uid='0' AND term='1264'; UPDATE grade_summaries SET a=0,b=30 WHERE uid='1' AND term='1264';",
    );
    const scope = courseTagScope(
      parseCourseFilters(new URLSearchParams(), term, "all"),
      ["higher-grades", "lower-grades"],
      prior,
    );
    expect(
      db
        .prepare(
          `WITH ${scope.ctes.join(",")} SELECT uid,tag FROM course_tags ORDER BY uid`,
        )
        .all(...(scope.values as any[])),
    ).toEqual([
      { uid: "0", tag: "higher-grades" },
      { uid: "1", tag: "lower-grades" },
    ]);
    db.close();
  });

  it("does not qualify instructors without a valid rating prior", () => {
    const { db } = fixture();
    const scope = courseTagScope(
      parseCourseFilters(new URLSearchParams(), term, "all"),
      ["rated-teacher"],
      null,
    );
    expect(
      db
        .prepare(`WITH ${scope.ctes.join(",")} SELECT * FROM course_tags`)
        .all(...(scope.values as any[])),
    ).toEqual([]);
    db.close();
  });
});
