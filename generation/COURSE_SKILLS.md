# Official outcomes and course skills

Outcomes are course-level source records, independent of LLM results. Guide
collection reads its structured learning-outcome blocks. Enrollment collection
reads explicit outcome fields when supplied; reconciliation also recovers them
from older archived search hits. A field's absence is not evidence that a course
has no outcomes. Enrollment's current public API availability still needs a
successful live response or real archived payload verification.

Each record retains text, source URL, explicit catalog year or term, and the
original archived fetch time when known. Identical text from different sources
remains separate. Cross-listed aliases resolve to one course identity. Replay
can populate these fields without recrawling when archived bytes contain them.

## Local source pilot

Download subject HTML from `https://guide.wisc.edu/courses/<subject>/` and supply
the saved bytes explicitly. This command archives those bytes, produces a
40-course source sample across five subjects, and creates 600 **pending**
classification decisions from 100 courses:

```sh
uv run --locked python -m uwcourses.skills_pilot \
  --guide comp_sci=/tmp/coursemap-guide-comp-sci.html \
  --guide stat=/tmp/coursemap-guide-stat.html \
  --guide psych=/tmp/coursemap-guide-psych.html \
  --guide chem=/tmp/coursemap-guide-chem.html \
  --guide history=/tmp/coursemap-guide-history.html \
  --output .coursemap/skills-pilot
```

The output directory must be new. `coverage.json` records source hashes and
coverage; `courses.jsonl` retains complete source outcomes. The annotation queue
uses one short official passage per course and six activity questions. It is a
starting evaluation sample, not a comprehensive labeled training corpus. Expand
the reviewed dataset for missing evidence, unrelated passages and each category
before enabling classification. Pending `gold: null, reviewed: false` rows cannot
be evaluated as human-reviewed unknown answers. See [CLASSIFICATION.md](CLASSIFICATION.md).

## Qwen extraction

Create or replay a source snapshot using the existing `uwcourses` commands,
then use the new profile and the versioned unified task:

```sh
uv run --locked uwcourses models-lock \
  --models-config inference/models.toml --profile course-skills-qwen38 \
  --output .coursemap/course-skills-models.json
uv run --locked python scripts/serve_inference.py --workspace .coursemap \
  --models-config .coursemap/course-skills-models.json \
  --profile course-skills-qwen38 --dry-run
uv run --locked uwcourses --workspace .coursemap enrich RUN_ID \
  --models-config .coursemap/course-skills-models.json \
  --profile course-skills-qwen38 \
  --task inference/tasks/course_enrichment.json --limit 40 --prepare-only
uv run --locked uwcourses --workspace .coursemap enrich-resume JOB_ID
```

Start the matching local model server by omitting `--dry-run` before resuming
the job. Existing inference tooling supplies server launch configuration;
website builds never launch inference. Use repeated `--course` arguments for an
explicit pilot selection. Preparation and actual inference are distinct.

Skills and activity tags require exact supporting quotes. Outcome citations bind
to a source URL and an index in the supplied official records. Missing evidence
produces empty results. Activities do not imply assignments, workload, difficulty,
or formal prerequisites. Release selection and HF publication remain explicit
local operations; no pilot automatically publishes a dataset or deploys a site.

Serving records add optional official outcomes and cited skill/activity data.
Older v6 datasets import with empty new fields. Course pages render the evidence
in initial HTML; search accepts the activity taxonomy tokens documented in the
classification guide.
