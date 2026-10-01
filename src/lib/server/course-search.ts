import { courseTagScope } from "./course-tags";
import type { CourseTag } from "$lib/course-tags";
import { error } from "@sveltejs/kit";
import { normalize } from "$lib/format";
import { isCourseCollection } from "$lib/course-collections";
import { compileCourseQuery, type CourseQuery } from "./course-query";

export function searchExpression(q: string, kind: string) {
  if (q.length > 200) error(400, "Query is too long");
  const text =
    kind === "course"
      ? q.replace(/\bCOMP\s+SCI\b/gi, "COMPSCI").replace(/\bCS\b/gi, "COMPSCI")
      : q;
  return (text.match(/[\p{L}\p{N}]+/gu) || [])
    .map((token) => '"' + token + '"*')
    .join(" AND ");
}

export function courseSearchScope(
  query: CourseQuery,
  q: string,
  ranking: string | null,
  history = false,
  highlights: {
    tags?: readonly CourseTag[];
    ratingPrior?: number | null;
    allTagSubjects?: boolean;
    projection?: { available: boolean; window: boolean };
  } = {},
) {
  if (ranking && !isCourseCollection(ranking))
    error(400, "Invalid course ranking");
  const compiled = compileCourseQuery(query);
  history ||= compiled.history || Boolean(ranking);
  const totals = "SUM(a+ab+b+bc+c+d+f)";
  const ctes = history
    ? [
        highlights.projection?.window
          ? "history AS (SELECT uid,grade_count,history_gpa FROM grade_windows WHERE term=?)"
          : `history AS (SELECT uid,${totals} grade_count,SUM(a*4+ab*3.5+b*3+bc*2.5+c*2+d)*1.0/NULLIF(${totals},0) history_gpa FROM grade_summaries WHERE term<=? AND CAST(term AS INTEGER)>? GROUP BY uid)`,
      ]
    : [];
  let from =
    "courses c" + (history ? " LEFT JOIN history h ON h.uid=c.uid" : "");
  const values: unknown[] = history
    ? highlights.projection?.window ? [query.term] : [query.term, Number(query.term) - 50]
    : [];
  const tags = [...new Set([...query.tags, ...(highlights.tags ?? [])])];
  if (tags.length) {
    const scope = courseTagScope(
      query,
      tags,
      highlights.ratingPrior ?? null,
      highlights.allTagSubjects,
      highlights.projection?.available,
    );
    ctes.push(...scope.ctes);
    values.push(...scope.values);
  }
  const prefix = ctes.length ? `WITH ${ctes.join(",")} ` : "";
  const expression = searchExpression(q, "course");
  if (expression) {
    from +=
      " JOIN (SELECT uid,bm25(search,0,0,12,6,1) score FROM search WHERE search MATCH ? AND kind=? UNION ALL SELECT uid,-1000000 score FROM aliases WHERE alias=?) m ON m.uid=c.uid";
    values.push(expression, "course", normalize(q));
  }
  values.push(...compiled.values);
  return {
    prefix,
    from,
    where: "1=1" + compiled.where + (ranking ? " AND h.grade_count>=100" : ""),
    values,
    history,
    expression,
  };
}
