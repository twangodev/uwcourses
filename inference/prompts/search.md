# Course search metadata

Write a short, complete summary (preferably under 180 characters), topics, skills,
assumed background, discovery phrases and activity_tags. Empty arrays are fine;
return null for this section if both the description and official outcomes are missing.

Support each factual claim with exact quotes, a canonical course_id, and its field.
Only the target course's title, description and official_learning_outcomes establish
what it teaches, including languages and tools. For an official outcome citation,
use field "official_learning_outcomes", its zero-based outcome_index, and exactly
that outcome's source_url. Copy a literal substring from its text; do not combine
outcomes or paraphrase quotations. Preserve differing sources and dated versions.
Use related course descriptions only for background explicitly required or recommended
by the target. Credit exclusions and overlapping courses do not establish assumed
background. Discovery phrases are search aids, not additional factual claims.

activity_tags is optional for historical results; emit it for new results. Use only
these labels and require a root course description or outcome quote for each:
- programming: students explicitly write, implement or debug computer programs.
- data-analysis: students explicitly analyze, model, interpret or visualize data.
- mathematical-reasoning: students explicitly construct proofs, derive mathematical
  results or reason with mathematical arguments.
- writing: students explicitly compose, revise or develop written work.
- lab-work: students explicitly conduct laboratory experiments or use lab methods.
- presentations: students explicitly deliver oral presentations or present work.
Classify activities students perform, not subjects merely discussed. A title, an
assessment assumption, a prerequisite, or a quoted mention of an activity is not
sufficient. Leave uncertain labels absent. Never infer assessment format, workload,
instructor quality, difficulty, career outcomes or formal prerequisites.
