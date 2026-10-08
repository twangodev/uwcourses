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
Every factual detail in a summary must be supported by its attached quotes. A true
detail elsewhere in the supplied source is not enough: attach that evidence too.
For example, if adding dates or the course name from the title to a description
summary, cite both the title and description. Use additional outcome citations
when the summary also lists content found only in the outcomes.

assumed_background describes only concepts or skills the root course text explicitly
states are prior knowledge, required preparation, or recommended preparation. Do not
infer background from course level, subject, credit equivalencies, or course titles.
Do not copy prerequisite course codes, standing, program membership, or enrollment
conditions into assumed_background; the requirements tree preserves those rules and
their alternative routes. In particular, a prerequisite course OR graduate standing
does not mean everyone must know that course's content. Related courses, credit
exclusions, and overlapping courses never add assumed_background by themselves.
An explicit statement that no prior experience is needed may be retained verbatim.
Otherwise leave assumed_background empty when no concepts or skills are stated.

Discovery phrases must describe source-supported content. Do not add tools,
programming languages, careers, degree levels, or methods merely associated with the
field. Graduate or undergraduate standing is an eligibility condition, not evidence
of a course's audience or degree classification. Search aids must not introduce
unsupported factual claims, even though they do not carry their own citations.

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

Apply the definitions conservatively:
- data-analysis requires explicit analysis or interpretation of datasets using
  statistical or computational methods. Analyzing historical sources, literature,
  art, legal arguments, or research articles is not that activity. A spectroscopy
  or instrumentation topic, structural analysis, or interpreting a spectrum alone
  does not establish statistical or computational dataset methods.
- mathematical-reasoning requires explicit mathematical proofs, arguments, or
  derivations. Explaining chemical reaction mechanisms, drawing electron-pushing
  arrows, or applying a scientific model does not establish mathematical reasoning
  unless the source explicitly describes the mathematical argument or derivation.
- programming requires students writing, modifying, or debugging programs. Merely
  discussing a programming language or software tool is insufficient.
- writing requires producing substantial written work; a general statement about
  written communication skills alone does not establish this activity.
- presentations requires delivering oral presentations or presenting work to an
  audience; communicating ideas, giving feedback, or oral communication skills alone
  does not establish this activity.
- lab-work requires students performing experiments or using laboratory instruments;
  studying experimental methods or selecting an experiment alone is insufficient.
