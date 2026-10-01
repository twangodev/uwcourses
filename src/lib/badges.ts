import { courseUrl, termName } from './format';
import { departmentName } from './departments';
import { tagThresholds, type CourseTag } from './course-tags';

export interface Badge {
  id: string;
  tag?: CourseTag;
  label: string;
  tone: 'positive' | 'negative' | 'caution' | 'neutral';
  evidence: string;
  sources: { label: string; href: string }[];
}
export interface BadgeRatings {
  bayesian_quality?: number | null;
  quality_count?: number;
  difficulty?: number | null;
  difficulty_count?: number;
  source_url?: string;
}
const valid = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
export function instructorBadges(ratings?: BadgeRatings | null): Badge[] {
  if (!ratings) return [];
  const sources = ratings.source_url ? [{ label: 'Captured RMP profile', href: ratings.source_url }] : [];
  const badges: Badge[] = [];
  if (valid(ratings.bayesian_quality) && ratings.bayesian_quality >= tagThresholds.quality && ratings.bayesian_quality <= 5 && (ratings.quality_count ?? 0) >= tagThresholds.qualityRatings)
    badges.push({ id: 'highly-rated', label: 'Highly rated', tone: 'positive', evidence: `${ratings.bayesian_quality.toFixed(2)}/5 Bayesian-adjusted quality from ${ratings.quality_count} quality ratings. Requires at least 4.0 and 10 ratings. All captured review dates and courses; not a course-specific rating.`, sources });
  if (valid(ratings.difficulty) && ratings.difficulty >= 3.5 && ratings.difficulty <= 5 && (ratings.difficulty_count ?? 0) >= 10)
    badges.push({ id: 'challenging', label: 'Challenging', tone: 'caution', evidence: `${ratings.difficulty.toFixed(2)}/5 reported difficulty from ${ratings.difficulty_count} difficulty ratings. Requires at least 3.5 and 10 ratings. All captured review dates and courses; difficulty does not measure teaching quality.`, sources });
  return badges;
}

export function courseBadges({ course, context, term, scope = 'school', instructors }: {
  course: any; context: any; term: string; scope?: string;
  instructors: { name?: string; instructor_url?: string; ratings?: BadgeRatings; terms?: { term: string }[] }[];
}): Badge[] {
  const badges: Badge[] = [];
  const rosterTerm = term || course.semester;
  const teachers = [...new Map(instructors.filter(i => i.terms?.some(t => t.term === rosterTerm) && instructorBadges(i.ratings).some(b => b.id === 'highly-rated')).map(i => [i.instructor_url || i.name, i])).values()];
  if (teachers.length) badges.push({ id: 'rated-teacher', tag: 'rated-teacher', label: 'Highly rated instructor', tone: 'positive', evidence: `${termName(rosterTerm)}: ${teachers.map(i => `${i.name || 'Instructor'} (${i.ratings!.bayesian_quality!.toFixed(2)}/5 adjusted; ${i.ratings!.quality_count} ratings)`).join('; ')}. At least one assigned instructor qualifies. This describes instructor reviews across courses, not a course rating.`, sources: teachers.flatMap(i => i.instructor_url ? [{ label: i.name || 'Instructor profile', href: i.instructor_url }] : []) });
  const gradeTerm = term ? Object.keys(context?.terms || {}).filter(t => t <= term && context.terms[t]?.count > 0).sort().at(-1) : '';
  const grades = term ? context?.terms[gradeTerm || ''] : context?.all;
  const reference = term ? context?.benchmarks.terms[gradeTerm || '']?.[scope] : context?.benchmarks.all[scope];
  if (grades?.count >= tagThresholds.letterGrades && valid(grades.gpa) && valid(reference?.gpa)) {
    const delta = grades.gpa - reference.gpa;
    if (Math.abs(delta) + Number.EPSILON * 4 >= tagThresholds.gradeDifference) badges.push({ id: 'grade-outcomes', tag: delta > 0 ? 'higher-grades' : 'lower-grades', label: delta > 0 ? 'Higher grades' : 'Lower grades', tone: delta > 0 ? 'positive' : 'negative', evidence: `${gradeTerm ? termName(gradeTerm) : 'All recorded terms'}${term && gradeTerm !== term ? ` · latest released grades before ${termName(term)}` : ''}: ${grades.gpa.toFixed(2)} GPA across ${grades.count.toLocaleString('en-US')} letter grades, versus ${reference.gpa.toFixed(2)} for ${scope === 'school' ? 'UW–Madison' : departmentName(scope)} (${reference.size} courses). Requires a difference of at least 0.20 and 30 letter grades. Historical outcomes, not predicted difficulty.`, sources: [{ label: 'Grade history and sources', href: courseUrl(course.course_id) + '#grades' }] });
  }
  const sections = [...new Map<string, any>((course.sections || []).filter((s: any) => s.term_id === rosterTerm && s.section_type === 'LEC' && valid(s.enrolled) && s.enrolled > 0).map((s: any) => [s.section_uid || `${s.term_id}:${s.section_type}:${s.section_number}`, s])).values()];
  const sizes = sections.map(s => s.enrolled as number).sort((a,b) => a-b);
  if (sizes.length) {
    const median = (sizes[Math.floor((sizes.length-1)/2)] + sizes[Math.floor(sizes.length/2)]) / 2;
    if (median <= tagThresholds.smallLecture || median >= tagThresholds.largeLecture) badges.push({ id: 'lecture-size', tag: median <= tagThresholds.smallLecture ? 'small-lectures' : 'large-lectures', label: median <= tagThresholds.smallLecture ? 'Small lectures' : 'Large lectures', tone: 'neutral', evidence: `${termName(rosterTerm)}: median ${median.toLocaleString('en-US')} enrolled students across ${sizes.length} recorded lecture section${sizes.length === 1 ? '' : 's'}. Small means 30 or fewer; large means 100 or more. Enrollment at scan time, not capacity or typical historical attendance.`, sources: [{ label: 'Sections and enrollment', href: courseUrl(course.course_id) + '#schedule' }] });
  }
  return badges;
}
