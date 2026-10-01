import { tagThresholds } from "./course-tags";

export interface GradePeer {
  uid: string;
  term: string;
  gpa: number;
  count: number;
  topShare: number;
  subjects: string[];
}
export interface Benchmark {
  size: number;
  gpa: number;
  topShare: number;
  count: number;
}
export type Benchmarks = Record<string, Benchmark | null>;

// Each course has equal weight. Grade count uses the median, not total enrollment.
export function benchmark(rows: GradePeer[]): Benchmark | null {
  const peers = rows.filter((row) => row.count >= tagThresholds.letterGrades);
  if (peers.length < tagThresholds.benchmarkCourses) return null;
  const counts = peers.map((row) => row.count).sort((a, b) => a - b);
  return {
    size: peers.length,
    gpa: peers.reduce((sum, row) => sum + row.gpa, 0) / peers.length,
    topShare: peers.reduce((sum, row) => sum + row.topShare, 0) / peers.length,
    count: (counts[Math.floor((counts.length - 1) / 2)] + counts[Math.floor(counts.length / 2)]) / 2,
  };
}
export function cohortBenchmarks(rows: GradePeer[]): Benchmarks {
  const subjects = new Map<string, GradePeer[]>();
  for (const row of rows) for (const subject of new Set(row.subjects)) {
    const group = subjects.get(subject) || [];
    group.push(row);
    subjects.set(subject, group);
  }
  return Object.fromEntries([
    ["school", benchmark(rows)],
    ...[...subjects].map(([subject, group]) => [subject, benchmark(group)]),
  ]);
}
// Input is canonical course/term data: repeated scrape observations are already removed.
export function aggregateTerms(rows: GradePeer[]): GradePeer[] {
  const courses = new Map<string, GradePeer>();
  for (const row of rows) {
    const old = courses.get(row.uid);
    if (!old) courses.set(row.uid, { ...row, subjects: [...row.subjects] });
    else {
      const count = old.count + row.count;
      old.gpa = (old.gpa * old.count + row.gpa * row.count) / count;
      old.topShare = (old.topShare * old.count + row.topShare * row.count) / count;
      old.count = count;
      old.subjects = [...new Set([...old.subjects, ...row.subjects])];
    }
  }
  return [...courses.values()];
}

export function metricColor(value: number | null, reference: number | null | undefined) {
  if (value == null || reference == null || Math.abs(value - reference) < 0.005) return "var(--text)";
  return value > reference ? "var(--positive)" : "var(--negative)";
}
