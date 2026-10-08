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
- programming: Writing, modifying, or debugging computer programs.
- data-analysis: Analyzing or interpreting datasets using statistical or computational methods.
- mathematical-reasoning: Constructing mathematical arguments, proofs, or deriving mathematical results.
- writing: Producing written arguments, reports, essays, or other substantial written work.
- lab-work: Performing laboratory experiments or working with laboratory instruments.
- presentations: Delivering oral presentations or presenting work to an audience.
Classify activities students perform, not subjects merely discussed. A title, an
assessment assumption, a prerequisite, or a quoted mention of an activity is not
sufficient. Leave uncertain labels absent. Never infer assessment format, workload,
instructor quality, difficulty, career outcomes or formal prerequisites.
